import cv2
import numpy as np

from sentinel_agent.snapshots import FrameBuffer, crop_box, save_snapshots


def test_crop_box_adds_margin_and_stays_inside_the_frame():
    # 40 px wide is padded to the 96 px minimum (28 px each side); 80 px tall gets 35 %.
    assert crop_box((240, 320, 3), (100, 100, 40, 80)) == (72, 72, 168, 208)
    x0, y0, x1, y1 = crop_box((240, 320, 3), (0, 0, 10, 10))  # tiny box at the corner
    assert (x0, y0) == (0, 0) and x1 >= 50 and y1 >= 50


def test_save_snapshots_writes_crop_and_scene(tmp_path, make_event):
    frame = np.zeros((240, 320, 3), np.uint8)
    frame[100:180, 100:140] = 255  # the "object"
    event = make_event(best_frame_index=3, best_bbox=(100, 100, 40, 80))
    name = save_snapshots(frame, event, tmp_path)
    crop = cv2.imread(str(tmp_path / name))
    scene = cv2.imread(str(tmp_path / f"{event.id}_scene.jpg"))
    assert crop.shape[:2] == (136, 96) and crop.mean() > 50  # the object is in the crop
    assert scene.shape == frame.shape


def test_event_without_box_has_no_snapshot(tmp_path, make_event):
    assert save_snapshots(np.zeros((10, 10, 3), np.uint8), make_event(), tmp_path) is None


def test_frame_buffer_round_trips_and_forgets_old_frames():
    buffer = FrameBuffer(max_age_seconds=2.0)
    frame = np.full((48, 64, 3), 120, np.uint8)
    for i in range(10):
        buffer.add(i, i * 0.5, frame)  # 0.0 .. 4.5 s
    assert buffer.get(0) is None  # older than 2 s
    restored = buffer.get(9)
    assert restored.shape == frame.shape and abs(int(restored.mean()) - 120) <= 2
    assert len(buffer) == 5


def test_events_point_at_their_most_confident_detection():
    from sentinel_agent.events.aggregator import cluster_into_events
    from sentinel_agent.pipeline import synthetic_detections

    detections = synthetic_detections(1)
    for event in cluster_into_events(detections):
        (best,) = [
            d
            for d in detections
            if d.frame_index == event.best_frame_index and d.bbox == event.best_bbox
        ]
        assert best.raw_confidence == event.max_raw_confidence
