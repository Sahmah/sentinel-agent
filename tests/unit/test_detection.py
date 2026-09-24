import cv2
import numpy as np

from sentinel_agent.detection.classical import ClassicalCVDetector
from sentinel_agent.detection.scenario import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    generate_scenario,
    label_detections,
)
from sentinel_agent.detection.zones import RESTRICTED_ZONE, point_in_zone


def _blank() -> np.ndarray:
    return np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), 24, dtype=np.uint8)


def _detect(frame: np.ndarray):
    return ClassicalCVDetector().detect(frame, camera_id="cam", frame_index=0, timestamp=0.0)


def test_point_in_zone_edges():
    x, y, w, h = RESTRICTED_ZONE
    assert point_in_zone((x, y))
    assert point_in_zone((x + w, y + h))
    assert not point_in_zone((x - 1, y))


def test_circle_is_person_square_is_object():
    frame = _blank()
    cv2.circle(frame, (60, 60), 10, (210, 210, 210), -1)
    cv2.rectangle(frame, (120, 150), (140, 170), (150, 150, 150), -1)
    labels = {d.label for d in _detect(frame)}
    assert labels == {"person", "object"}


def test_painted_zone_overlay_is_not_detected():
    frame = generate_scenario(n_frames=1, decoy_spawn_prob=0.0)[0].frame
    detections = _detect(frame)
    assert len(detections) == 1  # only the target, not the zone rectangle


def test_scenario_is_deterministic_per_seed():
    a = generate_scenario(seed=3, n_frames=20)
    b = generate_scenario(seed=3, n_frames=20)
    assert all(np.array_equal(fa.frame, fb.frame) for fa, fb in zip(a, b, strict=True))


def test_target_crosses_the_zone():
    frames = generate_scenario()
    assert any(f.target_in_zone for f in frames)
    assert not all(f.target_in_zone for f in frames)


def test_label_detections_marks_only_the_target():
    frame = generate_scenario(n_frames=1, decoy_spawn_prob=0.0)[0]
    far = _detect(frame.frame)[0].model_copy(update={"bbox": (0, 0, 5, 5)})
    near = _detect(frame.frame)[0]
    labeled = label_detections(frame, [near, far])
    assert [d.is_true_positive for d in labeled] == [True, False]
