"""`sentinel` command line.

    sentinel demo       synthetic scene, end to end, zero AWS
    sentinel webcam     live camera or a video file, with YOLO (needs the `vision` extra)
    sentinel serve-mcp  MCP server (stdio) over the recorded events
    sentinel eval-llm   grade the reasoning LLM against synthetic ground truth
    sentinel report     Markdown report of recorded events, in lab/reports/
    sentinel serve      HTTP API + dashboard at http://127.0.0.1:8000

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
from sentinel_agent.agent.llm import build_llm, vision_enabled
from sentinel_agent.capture import LatestFrameReader
from sentinel_agent.events.aggregator import cluster_into_events
from sentinel_agent.events.models import Event
from sentinel_agent.pipeline import (
    Decision,
    calibrator_from_reviews,
    decide,
    evaluate_calibration,
    fit_calibrator,
    synthetic_detections,
    synthetic_scene,
    to_record,
)
from sentinel_agent.report import lab_dir, write_report
from sentinel_agent.snapshots import FrameBuffer, save_snapshots, snapshot_dir
from sentinel_agent.storage import build_storage, describe_storage
from sentinel_agent.storage.base import EventFilter


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
    frames, detections = synthetic_scene(args.seed)
    events = cluster_into_events(detections)
    vision = vision_enabled()
    graph = build_graph(build_llm(), vision=vision)
    # Snapshots are cut before deciding: with vision on, the agent looks at them.
    snapshots: dict[str, str | None] = {}
    if vision or not args.no_store:
        for e in events:
            frame = frames.get(e.best_frame_index)
            snapshots[e.id] = save_snapshots(frame, e) if frame is not None else None
    decisions = [
        decide(graph, e, calibrator, snapshot_path=_snapshot_path(snapshots.get(e.id)))
        for e in events
    ]
    if not args.no_store:
        storage, run_id, started = build_storage(), uuid.uuid4().hex[:12], datetime.now(UTC)
        for d in decisions:
            storage.save(
                to_record(
                    d,
                    run_id=run_id,
                    source="demo",
                    run_started_at=started,
                    snapshot=snapshots.get(d.event.id),
                )
            )

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
        print(
            f"Saved {len(decisions)} events to {describe_storage()} (run {run_id}), "
            f"snapshots in {snapshot_dir()}/."
        )
        report = write_report(
            storage,
            title=f"Sentinel demo, seed {args.seed} (run {run_id})",
            filters=EventFilter(since=started),
            run_id=run_id,
            name=f"demo-{started:%Y%m%d-%H%M%S}-{run_id}",
        )
        print(f"Report: {report}")
    return 0


def _snapshot_path(name: str | None) -> str | None:
    return str(snapshot_dir() / name) if name else None


def _parse_zone(text: str) -> tuple[float, float, float, float]:
    parts = tuple(float(v) for v in text.split(","))
    if len(parts) != 4 or not all(0 <= v <= 1 for v in parts):
        raise argparse.ArgumentTypeError("zone must be four fractions x,y,w,h in [0, 1]")
    return parts  # type: ignore[return-value]


class EventWorker:
    """Runs the agent on closed events in a background thread, so a slow LLM call
    (seconds per event on Bedrock) doesn't freeze capture and the preview window.
    Events are handled one at a time, in the order they closed."""

    def __init__(
        self,
        graph,
        *,
        calibrator=None,
        snapshot_for: Callable[[str], str | None] | None = None,
        save: Callable[[Decision], None] | None = None,
        out=None,
    ):
        self.last_line = ""
        self.saved = 0
        self._graph = graph
        self._calibrator = calibrator
        self._snapshot_for = snapshot_for or (lambda event_id: None)
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
                d = decide(self._graph, event, self._calibrator, self._snapshot_for(event.id))
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
    import os

    import cv2

    # opencv-python points Qt at its own font folder (empty in the wheel) when imported,
    # and the preview window then warns on every frame; use the system fonts instead.
    if sys.platform == "linux" and os.path.isdir("/usr/share/fonts/truetype"):
        os.environ["QT_QPA_FONTDIR"] = "/usr/share/fonts/truetype"
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
        if is_camera:
            # Ask for MJPG: uncompressed YUYV frames are large enough that USB links with
            # less bandwidth (a camera forwarded into WSL with usbipd) deliver them
            # truncated, which OpenCV decodes as a solid green image.
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cv2.utils.logging.setLogLevel(log_level)
    if not capture.isOpened():
        print(f"Could not open video source {args.source!r}.", file=sys.stderr)
        if is_camera:
            print(
                "On WSL, attach the camera first with usbipd-win, or run this command from "
                "Windows (both in docs/webcam.md).",
                file=sys.stderr,
            )
        return 1

    detector = YoloDetector(load_yolo(args.model), zone_fraction=args.zone or DEFAULT_ZONE_FRACTION)
    # The first inference is ~40x slower (lazy init); pay for it before the clock starts.
    detector.detect(np.zeros((480, 640, 3), np.uint8), camera_id="", frame_index=0, timestamp=0)
    aggregator = StreamingAggregator(gap_seconds=args.gap)
    policy = DecisionPolicy(min_person_detections_outside_zone=args.min_detections)
    save = None
    calibrator = None
    frame_buffer = FrameBuffer()
    snapshots: dict[str, str] = {}  # event id -> crop file, written before the event is queued
    if not args.no_store:
        storage, run_id = build_storage(), uuid.uuid4().hex[:12]
        calibrator, n_reviewed = calibrator_from_reviews(storage, args.camera_id)

        def save(d: Decision) -> None:
            # run_started_at is set when the clock starts, before any event can close.
            storage.save(
                to_record(
                    d,
                    run_id=run_id,
                    source="webcam",
                    run_started_at=run_started_at,
                    snapshot=snapshots.pop(d.event.id, None),
                )
            )

    vision = vision_enabled()
    worker = EventWorker(
        build_graph(build_llm(), policy=policy, vision=vision),
        calibrator=calibrator,
        snapshot_for=lambda event_id: _snapshot_path(snapshots.get(event_id)),
        save=save,
    )

    def close_events(events: list[Event]) -> None:
        # Snapshots are cut here, in the capture thread that owns the frame buffer,
        # before the event is queued for the (slower) agent thread.
        if vision or not args.no_store:
            for event in events:
                frame = frame_buffer.get(event.best_frame_index)
                if frame is not None:
                    snapshots[event.id] = save_snapshots(frame, event)
        worker.submit(events)

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = 1 if is_camera else max(1, round(source_fps / args.fps))

    if calibrator is not None:
        print(f"p_cv is calibrated on {n_reviewed} events you reviewed for this camera.")
    else:
        print("p_cv is YOLO's raw confidence (marked *): review events in the dashboard")
        print("(at least 5 real and 5 false alarms) and it gets calibrated on your verdicts.")
    print("Press q in the video window to stop.\n")
    print(HEADER)

    started = time.monotonic()
    run_started_at = datetime.now(UTC)
    # Camera frames are analysed on a fixed schedule (0, 1/fps, 2/fps, ...). Scheduling
    # "1/fps after the last analysis" instead lets every frame boundary and detector run
    # overshoot, and 5 fps became 3.6 in practice.
    period = 1 / args.fps
    next_due = 0.0
    frame_index = -1 if not is_camera else 0
    # A live camera is drained by its own thread (see capture.py); files are read in order.
    reader = LatestFrameReader(capture) if is_camera else None
    analysed = 0
    detections = []

    try:
        while True:
            if reader is not None:
                ok, frame, frame_index = reader.read(frame_index)
            else:
                ok, frame = capture.read()
                frame_index += 1
            if not ok:
                break
            now = time.monotonic() - started if is_camera else frame_index / source_fps
            if args.max_seconds and now >= args.max_seconds:
                break
            due = now >= next_due if is_camera else frame_index % step == 0
            if due:
                # Catch up after a slow frame, but never queue a burst of analyses.
                next_due = max(next_due + period, now)
                analysed += 1
                detections = detector.detect(
                    frame, camera_id=args.camera_id, frame_index=frame_index, timestamp=now
                )
                aggregator.add(detections)
                if vision or not args.no_store:
                    frame_buffer.add(frame_index, now, frame)
                close_events(aggregator.pop_closed(now))

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
        if reader is not None:
            reader.close()
        capture.release()
        if not args.no_window:
            cv2.destroyAllWindows()

    elapsed = time.monotonic() - started
    close_events(aggregator.flush())
    worker.close()
    print(
        f"\n{analysed} frames analysed in {elapsed:.1f} s ({analysed / max(elapsed, 1e-9):.1f} fps)"
    )
    if not args.no_store:
        print(f"Saved {worker.saved} events to {describe_storage()} (run {run_id}).")
        report = write_report(
            storage,
            title=f"Sentinel webcam, {args.camera_id} (run {run_id})",
            filters=EventFilter(since=run_started_at),
            run_id=run_id,
            name=f"webcam-{run_started_at:%Y%m%d-%H%M%S}-{run_id}",
        )
        print(f"Report: {report}")
    return 0


def _parse_seeds(text: str) -> list[int]:
    """ "1-5" or "1,3,7" (or a mix: "1-3,9")."""
    seeds: list[int] = []
    for part in text.split(","):
        first, _, last = part.partition("-")
        seeds += range(int(first), int(last or first) + 1)
    return seeds


def cmd_eval_llm(args: argparse.Namespace) -> int:
    import json
    import os

    from sentinel_agent.evaluation import evaluate_llm

    # Calibration scenes are kept apart from the evaluated ones (seeds 1000+).
    calibration_seeds = list(range(1000, 1000 + args.calibration_scenes))
    calibrator = fit_calibrator([d for s in calibration_seeds for d in synthetic_detections(s)])
    if vision_enabled():
        print(
            "Note: SENTINEL_LLM_VISION is ignored here. The synthetic targets are drawn shapes,\n"
            "so an image-reading model would rightly doubt them; vision needs real, reviewed\n"
            "video to be graded.\n"
        )
    graph = build_graph(build_llm())
    print(f"Evaluating on synthetic seeds {args.seeds} (backend: {_backend_name()})\n")
    print(f"{'seed':>4} {'label':<7} {'dets':>4} {'zone':<4} {'truth':<5} {'p_llm':>5}  action")

    def progress(r) -> None:
        p = " fail" if r.p_llm is None else f"{r.p_llm:5.2f}"
        truth = "real" if r.is_real else "false"
        zone = "yes" if r.in_zone else "no"
        print(
            f"{r.seed:>4} {r.label:<7} {r.detection_count:>4} {zone:<4} {truth:<5} {p}  "
            f"{r.action}  ({r.seconds:.1f}s)",
            flush=True,
        )

    report = evaluate_llm(graph, _parse_seeds(args.seeds), calibrator, progress=progress)
    m = report.metrics()

    def fmt(value) -> str:
        return "-" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)

    print(
        f"\n{m['events']} events ({m['real']} real), {m['parse_failures']} unparseable replies\n"
        f"p_llm separates real from false: AUROC {fmt(m['auroc'])} "
        f"(mean {fmt(m['mean_p_llm_real'])} real vs {fmt(m['mean_p_llm_false'])} false)\n"
        f"p_llm calibration: ECE {fmt(m['ece'])}, Brier {fmt(m['brier'])}\n"
        f"Decisions: {m['real_alerted']}/{m['real']} real events alerted, "
        f"{m['false_alerted']} false alerts, {m['human_review']} sent to human review\n"
        f"Median time per event: {fmt(m['median_seconds'])} s"
    )
    # Every run is kept, so prompt or model changes can be compared later.
    path = args.json or str(
        lab_dir() / "evals" / f"eval-{_backend_name().replace('/', '-').replace(':', '-')}"
        f"-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "backend": _backend_name(),
                "vision": False,
                "seeds": args.seeds,
                "metrics": m,
                "events": [r.__dict__ for r in report.results],
            },
            f,
            indent=2,
        )
    print(f"Metrics written to {path}")
    return 0


def _backend_name() -> str:
    import os

    backend = os.environ.get("SENTINEL_LLM_BACKEND", "demo")
    if backend == "ollama":
        return f"ollama/{os.environ.get('SENTINEL_OLLAMA_MODEL', 'gemma3:4b')}"
    return backend


def cmd_report(args: argparse.Namespace) -> int:
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(hours=args.hours)
    path = write_report(
        build_storage(),
        title=f"Sentinel report, last {args.hours:g} h"
        + (f", {args.camera_id}" if args.camera_id else ""),
        filters=EventFilter(camera_id=args.camera_id, since=since),
    )
    print(f"Report: {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from pathlib import Path

    import uvicorn

    from sentinel_agent.api import build_app

    # A checkout serves frontend/build; an installed release serves the copy bundled
    # into the package (sentinel_agent/dashboard, added by the release workflow).
    frontend = Path(args.frontend) if args.frontend else Path("frontend/build")
    if not frontend.is_dir() and not args.frontend:
        frontend = Path(__file__).parent / "dashboard"
    if not frontend.is_dir():
        print("No dashboard build found (see frontend/README.md); serving the API only.")
    print(f"Sentinel API on http://{args.host}:{args.port} (events from {describe_storage()})")
    uvicorn.run(build_app(frontend=frontend), host=args.host, port=args.port, log_level="warning")
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

    srv = sub.add_parser("serve", help="HTTP API and dashboard over the recorded events")
    srv.add_argument("--host", default="127.0.0.1", help="no auth: keep it on localhost")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument(
        "--frontend",
        help="built dashboard to serve (default: frontend/build, else the bundled one)",
    )
    srv.set_defaults(func=cmd_serve)

    ev = sub.add_parser("eval-llm", help="grade the reasoning LLM on synthetic ground truth")
    ev.add_argument("--seeds", default="1-3", help='scenes to evaluate, e.g. "1-5" or "1,4"')
    ev.add_argument("--calibration-scenes", type=int, default=5)
    ev.add_argument("--json", help="where to write the metrics (default: lab/evals/)")
    ev.set_defaults(func=cmd_eval_llm)

    rp = sub.add_parser("report", help="write a Markdown report of recorded events to lab/")
    rp.add_argument("--hours", type=float, default=24, help="how far back (default 24)")
    rp.add_argument("--camera-id", help="only this camera")
    rp.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
