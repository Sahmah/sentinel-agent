"""Deep-learning detector for real camera/video input, via Ultralytics YOLO.

Optional: needs the `vision` extra (`uv sync --extra vision`). Ultralytics is
AGPL-3.0 licensed — see the README before using this in anything you ship.

Same `Detector` protocol as `ClassicalCVDetector`, so the rest of the pipeline
does not know which one it is talking to. Labels are YOLO's COCO class names
("person", "car", "cell phone", ...); only "person" gets special treatment
downstream.
"""

from pathlib import Path
from typing import Any

import numpy as np

from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.zones import point_in_zone

DEFAULT_MODEL = "yolo26n.pt"
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
    ):
        """`model` is a loaded Ultralytics model (anything with `.names` and
        `.predict()`); defaults to YOLO26n. Injectable so tests need no torch."""
        self.model = model if model is not None else load_yolo()
        self.conf_threshold = conf_threshold
        self.zone_fraction = zone_fraction

    def detect(
        self, frame: np.ndarray, *, camera_id: str, frame_index: int, timestamp: float
    ) -> list[Detection]:
        result = self.model.predict(frame, conf=self.conf_threshold, verbose=False)[0]
        zone = zone_in_pixels(frame.shape, self.zone_fraction)
        boxes = result.boxes

        detections: list[Detection] = []
        for (x1, y1, x2, y2), conf, cls in zip(
            boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), strict=True
        ):
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
                )
            )
        return detections
