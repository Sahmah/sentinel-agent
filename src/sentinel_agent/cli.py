"""`sentinel` command line.

    sentinel demo       synthetic scene, end to end, zero AWS
    sentinel webcam     live camera or a video file, with YOLO (needs the `vision` extra)
    sentinel serve-mcp  MCP server (stdio) over the recorded events

The LLM backend comes from SENTINEL_LLM_BACKEND (`demo` by default; see agent/llm.py).
Decided events are stored per SENTINEL_STORAGE_BACKEND (SQLite by default; see storage/).
"""

import argparse
import queue
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from sentinel_agent.agent.graph import DecisionPolicy, build_graph
from sentinel_agent.agent.llm import build_llm
from sentinel_agent.events.aggregator import cluster_into_events
from sentinel_agent.events.models import Event
from sentinel_agent.pipeline import (
    Decision,
    decide,
    evaluate_calibration,
    fit_calibrator,
    synthetic_detections,
    to_record,
)
from sentinel_agent.storage import build_storage, describe_storage


def format_decision(d: Decision) -> str:
    e, s = d.event, d.state
    p_llm = s.get("llm_confidence")
    zone = "yes" if e.entered_restricted_zone else "no"
    return (
        f"{e.label:<10} {e.start_ts:6.1f}-{e.end_ts:<6.1f} {e.detection_count:>4}  {zone:<4} "
        f"{d.p_cv:5.2f}{'' if d.calibrated else '*'}  "
        f"{'  -  ' if p_llm is None else f'{p_llm:5.2f}'}  "
        f"{s.get('severity') or '-':<8} {s['action']}"
    )


HEADER = (
    f"{'label':<10} {'time (s)':<13} {'dets':>4}  {'zone':<4} {'p_cv':>5}  {'p_llm':>5}  "
    f"{'severity':<8} action"
)


def cmd_demo(args: argparse.Namespace) -> int:
    # Fit on scenes other than the one evaluated, so the reported ECE is out of sample.
    seeds = [args.seed + i for i in range(1, args.calibration_scenes + 1)]
    print(f"Calibrating on synthetic scenes {seeds[0]}-{seeds[-1]}...")
    calibrator = fit_calibrator([d for s in seeds for d in synthetic_detections(s)])

    print(f"Running the pipeline on synthetic seed {args.seed}...\n")
    detections = synthetic_detections(args.seed)
    events = cluster_into_events(detections)
    graph = build_graph(build_llm())
    decisions = [decide(graph, e, calibrator) for e in events]
    if not args.no_store:
        storage, run_id, started = build_storage(), uuid.uuid4().hex[:12], datetime.now(UTC)
        for d in decisions:
            storage.save(to_record(d, run_id=run_id, source="demo", run_started_at=started))

    print(HEADER)
    for d in decisions:
        truth = (
            ""
            if d.event.is_true_positive is None
            else ("  (real)" if d.event.is_true_positive else "  (false positive)")
        )
        print(format_decision(d) + truth)
        if d.state.get("reasoning"):
            print(f"{'':<12}{d.state['reasoning']}")

    report = evaluate_calibration(calibrator, detections)
    counts = Counter(d.state["action"] for d in decisions)
    print(
        f"\n{len(detections)} detections -> {len(events)} events: "
        + ", ".join(f"{n} {action}" for action, n in counts.most_common())
    )
    print(
        f"Calibration, out of sample ({report.n_detections} detections): "
        f"ECE {report.raw_ece:.3f} -> {report.calibrated_ece:.3f}, "
        f"Brier {report.raw_brier:.3f} -> {report.calibrated_brier:.3f}"
    )
    if not args.no_store:
        print(f"Saved {len(decisions)} events to {describe_storage()} (run {run_id}).")
    return 0


def _parse_zone(text: str) -> tuple[float, float, float, float]:
    parts = tuple(float(v) for v in text.split(","))
    if len(parts) != 4 or not all(0 <= v <= 1 for v in parts):
        raise argparse.ArgumentTypeError("zone must be four fractions x,y,w,h in [0, 1]")
    return parts  # type: ignore[return-value]


class EventWorker:
    """Runs the agent on closed events in a background thread, so a slow LLM call
    (seconds per event on Bedrock) doesn't freeze capture and the preview window.
    Events are handled one at a time, in the order they closed."""

    def __init__(self, graph, *, save: Callable[[Decision], None] | None = None, out=None):
        self.last_line = ""
        self.saved = 0
        self._graph = graph
        self._save = save
        self._out = out
        self._queue: queue.Queue[Event | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, events: list[Event]) -> None:
        for event in events:
            self._queue.put(event)

    def close(self) -> None:
        """Wait for every submitted event to be decided."""
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        out = self._out or sys.stdout
        while (event := self._queue.get()) is not None:
            try:
                d = decide(self._graph, event)
            except Exception as exc:  # keep the stream alive if one LLM call fails
                print(f"agent failed on {event.label} at {event.start_ts:.1f}s: {exc}", file=out)
                continue
            if self._save is not None:
                try:
                    self._save(d)
                    self.saved += 1
                except Exception as exc:  # a storage hiccup shouldn't stop the camera either
                    print(f"could not save {event.label} at {event.start_ts:.1f}s: {exc}", file=out)
            self.last_line = f"{event.label}: {d.state['action']}"
            print(format_decision(d), file=out)
            if d.state.get("reasoning"):
                print(f"{'':<12}{d.state['reasoning']}", file=out)


def _draw_preview(cv2, frame, zone, detections, status: str) -> None:
    zx, zy, zw, zh = zone
    cv2.rectangle(frame, (zx, zy), (zx + zw, zy + zh), (0, 0, 200), 2)
    for det in detections:
        x, y, w, h = det.bbox
        color = (0, 0, 255) if det.in_restricted_zone else (0, 200, 0)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(
            frame,
            f"{det.label} {det.raw_confidence:.2f}",
            (x, max(12, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )
    cv2.putText(
        frame, status, (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
    )


def cmd_webcam(args: argparse.Namespace) -> int:
    import cv2
    import numpy as np

    from sentinel_agent.detection.yolo import (
        DEFAULT_ZONE_FRACTION,
        YoloDetector,
        load_yolo,
        zone_in_pixels,
    )
    from sentinel_agent.events.stream import StreamingAggregator

    is_camera = args.source.isdigit()
    # OpenCV logs a wall of backend errors when a source fails to open; our own
    # message below says what to do, so keep only that.
    log_level = cv2.utils.logging.getLogLevel()
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    if is_camera and sys.platform == "win32":
        # The default Media Foundation backend can take a minute to open a USB webcam
        # (60 s measured on a Logitech C270); DirectShow opens it in under a second.
        capture = cv2.VideoCapture(int(args.source), cv2.CAP_DSHOW)
    else:
        capture = cv2.VideoCapture(int(args.source) if is_camera else args.source)
    cv2.utils.logging.setLogLevel(log_level)
    if not capture.isOpened():
        print(f"Could not open video source {args.source!r}.", file=sys.stderr)
        if is_camera:
            print(
                "On WSL the webcam is usually not visible to Linux; run this command from "
                "Windows instead (see docs/webcam.md).",
                file=sys.stderr,
            )
        return 1

    detector = YoloDetector(load_yolo(args.model), zone_fraction=args.zone or DEFAULT_ZONE_FRACTION)
    # The first inference is ~40x slower (lazy init); pay for it before the clock starts.
    detector.detect(np.zeros((480, 640, 3), np.uint8), camera_id="", frame_index=0, timestamp=0)
    aggregator = StreamingAggregator(gap_seconds=args.gap)
    policy = DecisionPolicy(min_person_detections_outside_zone=args.min_detections)
    save = None
    if not args.no_store:
        storage, run_id = build_storage(), uuid.uuid4().hex[:12]

        def save(d: Decision) -> None:
            # run_started_at is set when the clock starts, before any event can close.
            storage.save(
                to_record(d, run_id=run_id, source="webcam", run_started_at=run_started_at)
            )

    worker = EventWorker(build_graph(build_llm(), policy=policy), save=save)
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = 1 if is_camera else max(1, round(source_fps / args.fps))

    print("p_cv is YOLO's raw confidence (marked *): live input has no ground truth to")
    print("calibrate against. Press q in the video window to stop.\n")
    print(HEADER)

    started = time.monotonic()
    run_started_at = datetime.now(UTC)
    last_processed = float("-inf")
    frame_index = -1
    analysed = 0
    detections = []

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
            now = time.monotonic() - started if is_camera else frame_index / source_fps
            if args.max_seconds and now >= args.max_seconds:
                break
            due = now - last_processed >= 1 / args.fps if is_camera else frame_index % step == 0
            if due:
                last_processed = now
                analysed += 1
                detections = detector.detect(
                    frame, camera_id=args.camera_id, frame_index=frame_index, timestamp=now
                )
                aggregator.add(detections)
                worker.submit(aggregator.pop_closed(now))

            if not args.no_window:
                # Every frame is shown; between analysed frames the last boxes are redrawn.
                zone = zone_in_pixels(frame.shape, detector.zone_fraction)
                _draw_preview(cv2, frame, zone, detections, worker.last_line)
                cv2.imshow("sentinel-agent", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        capture.release()
        if not args.no_window:
            cv2.destroyAllWindows()

    elapsed = time.monotonic() - started
    worker.submit(aggregator.flush())
    worker.close()
    print(
        f"\n{analysed} frames analysed in {elapsed:.1f} s ({analysed / max(elapsed, 1e-9):.1f} fps)"
    )
    if not args.no_store:
        print(f"Saved {worker.saved} events to {describe_storage()} (run {run_id}).")
    return 0


def cmd_serve_mcp(args: argparse.Namespace) -> int:
    from sentinel_agent.mcp_server.server import build_server

    # stdout is the MCP channel: nothing else may be printed to it.
    build_server().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the pipeline on a synthetic scene (no AWS, no GPU)")
    demo.add_argument("--seed", type=int, default=1, help="scene to evaluate on")
    demo.add_argument(
        "--calibration-scenes",
        type=int,
        default=5,
        help="number of other scenes (seed+1, seed+2, ...) to fit calibration on",
    )
    demo.add_argument("--no-store", action="store_true", help="don't save the events")
    demo.set_defaults(func=cmd_demo)

    webcam = sub.add_parser("webcam", help="run on a webcam or video file with YOLO")
    webcam.add_argument("--source", default="0", help="camera index (0, 1, ...) or video path")
    webcam.add_argument("--model", default="yolo26n.pt", help="Ultralytics weights")
    webcam.add_argument("--fps", type=float, default=5.0, help="frames analysed per second")
    webcam.add_argument(
        "--gap", type=float, default=1.5, help="seconds unseen before an event closes"
    )
    webcam.add_argument("--zone", type=_parse_zone, help="restricted zone as x,y,w,h fractions")
    webcam.add_argument(
        "--min-detections",
        type=int,
        default=3,
        help="frames a person outside the zone must be seen in before the agent reasons about it",
    )
    webcam.add_argument("--camera-id", default="webcam")
    webcam.add_argument("--max-seconds", type=float, help="stop after this many seconds")
    webcam.add_argument("--no-window", action="store_true", help="no preview window")
    webcam.add_argument("--no-store", action="store_true", help="don't save the events")
    webcam.set_defaults(func=cmd_webcam)

    serve = sub.add_parser("serve-mcp", help="MCP server (stdio) to query the recorded events")
    serve.set_defaults(func=cmd_serve_mcp)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
