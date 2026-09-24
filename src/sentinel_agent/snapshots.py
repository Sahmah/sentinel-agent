"""Event snapshots: the moment an event is about, saved as images.

For each event two JPEGs are written, named after the event id:
- `<id>.jpg`: a crop around the highest-confidence detection (with a margin,
  so the object is seen in context), which is what a person or a vision LLM
  looks at first;
- `<id>_scene.jpg`: the whole frame with that box drawn.

Live video keeps only the frames it analysed, JPEG-encoded, in a `FrameBuffer`
bounded by age: an event can last up to `max_event_seconds`, so its best frame
may be that old when the event closes.
"""

import os
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

from sentinel_agent.events.models import Event

DEFAULT_DIR = "snapshots"
CROP_MARGIN = 0.35  # of the box size, on each side
MIN_CROP_SIDE = 96  # px; tiny boxes are padded up so the crop stays readable


def snapshot_dir() -> Path:
    return Path(os.environ.get("SENTINEL_SNAPSHOT_DIR", DEFAULT_DIR))


def crop_name(event_id: str) -> str:
    return f"{event_id}.jpg"


def scene_name(event_id: str) -> str:
    return f"{event_id}_scene.jpg"


def crop_box(
    frame_shape: tuple[int, ...], bbox: tuple[int, int, int, int], *, margin: float = CROP_MARGIN
) -> tuple[int, int, int, int]:
    """The region to cut out, as x0, y0, x1, y1, clamped to the frame."""
    height, width = frame_shape[:2]
    x, y, w, h = bbox
    pad_x = max(int(w * margin), (MIN_CROP_SIDE - w) // 2, 0)
    pad_y = max(int(h * margin), (MIN_CROP_SIDE - h) // 2, 0)
    x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
    x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
    return x0, y0, x1, y1


def save_snapshots(frame: np.ndarray, event: Event, directory: Path | None = None) -> str | None:
    """Write the crop and the scene for `event`. Returns the crop's file name,
    or None when the event has no box to crop."""
    if event.best_bbox is None:
        return None
    directory = directory or snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)

    x0, y0, x1, y1 = crop_box(frame.shape, event.best_bbox)
    cv2.imwrite(str(directory / crop_name(event.id)), frame[y0:y1, x0:x1])

    scene = frame.copy()
    x, y, w, h = event.best_bbox
    color = (0, 0, 255) if event.entered_restricted_zone else (0, 200, 0)
    cv2.rectangle(scene, (x, y), (x + w, y + h), color, 2)
    cv2.putText(scene, event.label, (x, max(12, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.imwrite(str(directory / scene_name(event.id)), scene)
    return crop_name(event.id)


class FrameBuffer:
    """Recent frames by index, JPEG-encoded (~30 KB each instead of ~900 KB raw)."""

    def __init__(self, *, max_age_seconds: float = 40.0, quality: int = 85):
        self.max_age_seconds = max_age_seconds
        self.quality = quality
        self._frames: OrderedDict[int, tuple[float, bytes]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._frames)

    def add(self, frame_index: int, timestamp: float, frame: np.ndarray) -> None:
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if ok:
            self._frames[frame_index] = (timestamp, jpeg.tobytes())
        while self._frames:
            oldest_index, (oldest_ts, _) = next(iter(self._frames.items()))
            if timestamp - oldest_ts <= self.max_age_seconds:
                break
            del self._frames[oldest_index]

    def get(self, frame_index: int) -> np.ndarray | None:
        entry = self._frames.get(frame_index)
        if entry is None:
            return None
        return cv2.imdecode(np.frombuffer(entry[1], np.uint8), cv2.IMREAD_COLOR)
