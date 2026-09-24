"""Deep-learning detector for real camera/video input, via Ultralytics YOLO.

Optional: needs the `vision` extra (`uv sync --extra vision`). Ultralytics is
AGPL-3.0 licensed — see the README before using this in anything you ship.

Same `Detector` protocol as `ClassicalCVDetector`, so the rest of the pipeline
does not know which one it is talking to. Labels are YOLO's COCO class names
("person", "car", "cell phone", ...); only "person" gets special treatment
downstream, so by default only people are detected.

By default frames go through Ultralytics' ByteTrack, which gives each box a
`track_id` that stays with the same object across frames (a Kalman motion model
plus a second matching pass for low-confidence boxes, e.g. someone partly
occluded). The aggregator groups by that id, so two people crossing each other
keep separate events. YOLO26 is NMS-free, so there is no `iou`/`agnostic_nms`
to tune: duplicate boxes within a frame are not the problem, identity across
frames is.
"""

from pathlib import Path
from typing import Any

import numpy as np

from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.zones import point_in_zone

DEFAULT_MODEL = "yolo26n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_CLASSES = ("person",)
WEIGHTS_DIR = Path.home() / ".cache" / "sentinel-agent"

# The restricted zone as fractions of the frame (x, y, w, h), since webcam
# resolutions vary. Default: the right ~40% of the image.
DEFAULT_ZONE_FRACTION = (0.58, 0.05, 0.4, 0.9)


def zone_in_pixels(
    frame_shape: tuple[int, ...], zone_fraction: tuple[float, float, float, float]
) -> tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    fx, fy, fw, fh = zone_fraction
    return int(fx * width), int(fy * height), int(fw * width), int(fh * height)


def load_yolo(model: str = DEFAULT_MODEL) -> Any:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ImportError(
            "The YOLO detector needs the optional `vision` extra: uv sync --extra vision"
        ) from exc
    path = Path(model)
    if not path.is_absolute() and path.parent == Path("."):
        # Keep downloaded weights out of the working directory / repo.
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        path = WEIGHTS_DIR / path
    return YOLO(str(path))


class YoloDetector:
    def __init__(
        self,
        model: Any = None,
        *,
        conf_threshold: float = 0.35,
        zone_fraction: tuple[float, float, float, float] = DEFAULT_ZONE_FRACTION,
        classes: tuple[str, ...] | None = DEFAULT_CLASSES,
        tracker: str | None = DEFAULT_TRACKER,
    ):
        """`model` is a loaded Ultralytics model (anything with `.names`,
        `.predict()` and `.track()`); defaults to YOLO26n. Injectable so tests
        need no torch. `classes` are COCO names to keep (None keeps all);
        `tracker` is an Ultralytics tracker config (None: no tracking, boxes
        have no `track_id` and the aggregator falls back to center distance)."""
        self.model = model if model is not None else load_yolo()
        self.conf_threshold = conf_threshold
        self.zone_fraction = zone_fraction
        self.tracker = tracker
        self.class_ids = None if classes is None else _class_ids(self.model.names, classes)

    def detect(
        self, frame: np.ndarray, *, camera_id: str, frame_index: int, timestamp: float
    ) -> list[Detection]:
        if self.tracker is None:
            result = self.model.predict(
                frame, conf=self.conf_threshold, classes=self.class_ids, verbose=False
            )[0]
        else:
            # No `conf` here: track() then feeds the tracker boxes down to 0.1, which
            # ByteTrack's second pass uses to keep identities through occlusions. Only
            # boxes above our threshold become detections (below), so p_cv means the
            # same thing with or without tracking.
            result = self.model.track(
                frame, persist=True, tracker=self.tracker, classes=self.class_ids, verbose=False
            )[0]
        zone = zone_in_pixels(frame.shape, self.zone_fraction)
        boxes = result.boxes
        ids = boxes.id.tolist() if getattr(boxes, "id", None) is not None else None
        if self.tracker is not None and ids is None:
            # No confirmed track yet (ByteTrack confirms a new object on its second
            # frame). Ultralytics then hands back the raw boxes without ids; passing
            # them on would open one-frame events for objects about to get a track.
            return []

        detections: list[Detection] = []
        for i, ((x1, y1, x2, y2), conf, cls) in enumerate(
            zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), strict=True)
        ):
            if conf < self.conf_threshold:
                continue
            x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
            detections.append(
                Detection(
                    camera_id=camera_id,
                    frame_index=frame_index,
                    timestamp=timestamp,
                    label=str(self.model.names[int(cls)]),
                    bbox=(x, y, w, h),
                    raw_confidence=float(conf),
                    in_restricted_zone=point_in_zone((x + w // 2, y + h // 2), zone),
                    track_id=None if ids is None else int(ids[i]),
                )
            )
        return detections


def _class_ids(names: dict[int, str], classes: tuple[str, ...]) -> list[int]:
    ids = {name: i for i, name in names.items()}
    unknown = [c for c in classes if c not in ids]
    if unknown:
        raise ValueError(f"Unknown class name(s) {unknown}; the model knows {sorted(ids)}")
    return [ids[c] for c in classes]
