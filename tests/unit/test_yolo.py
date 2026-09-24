"""YoloDetector with an injected fake model — no torch/ultralytics needed."""

from types import SimpleNamespace

import numpy as np
import pytest

from sentinel_agent.detection.yolo import WEIGHTS_DIR, YoloDetector, zone_in_pixels


class _FakeYolo:
    names = {0: "person", 2: "car"}

    def __init__(self, boxes: list[tuple[list[float], float, int]]):
        self.boxes = boxes
        self.calls: list[dict] = []

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        xyxy = np.array([b for b, _, _ in self.boxes], dtype=float).reshape(-1, 4)
        conf = np.array([c for _, c, _ in self.boxes], dtype=float)
        cls = np.array([k for _, _, k in self.boxes], dtype=float)
        return [SimpleNamespace(boxes=SimpleNamespace(xyxy=xyxy, conf=conf, cls=cls))]


FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_zone_in_pixels_scales_with_frame():
    assert zone_in_pixels((480, 640, 3), (0.5, 0.0, 0.5, 1.0)) == (320, 0, 320, 480)


def test_boxes_become_detections_with_class_names_and_zone():
    model = _FakeYolo([([10, 10, 60, 110], 0.9, 0), ([500, 100, 600, 300], 0.6, 2)])
    detector = YoloDetector(model, zone_fraction=(0.5, 0.0, 0.5, 1.0), conf_threshold=0.4)
    left, right = detector.detect(FRAME, camera_id="cam", frame_index=3, timestamp=0.6)

    assert (left.label, left.bbox, left.in_restricted_zone) == ("person", (10, 10, 50, 100), False)
    assert (right.label, right.in_restricted_zone) == ("car", True)
    assert right.raw_confidence == pytest.approx(0.6)
    assert model.calls[0]["conf"] == 0.4


def test_no_boxes_no_detections():
    assert (
        YoloDetector(_FakeYolo([])).detect(FRAME, camera_id="c", frame_index=0, timestamp=0) == []
    )


def test_real_yolo_finds_people():
    """Only runs with the `vision` extra installed and weights already cached (no downloads)."""
    pytest.importorskip("ultralytics")
    if not (WEIGHTS_DIR / "yolo26n.pt").exists():
        pytest.skip("yolo26n.pt not cached; run `sentinel webcam` once to download it")
    import cv2
    from ultralytics.utils import ASSETS

    from sentinel_agent.detection.yolo import load_yolo

    frame = cv2.imread(str(ASSETS / "bus.jpg"))
    detections = YoloDetector(load_yolo()).detect(frame, camera_id="c", frame_index=0, timestamp=0)
    assert sum(d.label == "person" for d in detections) >= 3
