from sentinel_agent.detection.models import Detection
from sentinel_agent.events.stream import StreamingAggregator


def _det(t: float, x: int = 100) -> Detection:
    return Detection(
        camera_id="cam",
        frame_index=int(t * 5),
        timestamp=t,
        label="person",
        bbox=(x, 100, 40, 80),
        raw_confidence=0.8,
    )


def test_event_closes_only_after_gap():
    agg = StreamingAggregator(gap_seconds=1.0)
    agg.add([_det(0.0), _det(0.2), _det(0.4)])
    assert agg.pop_closed(now=1.0) == []
    (event,) = agg.pop_closed(now=1.5)
    assert event.detection_count == 3
    assert agg.flush() == []  # emitted detections left the buffer


def test_open_track_is_kept_while_a_finished_one_is_emitted():
    agg = StreamingAggregator(gap_seconds=1.0)
    agg.add([_det(0.0, x=20), _det(0.2, x=20)])  # left the scene early
    agg.add([_det(t / 5, x=400) for t in range(15)])  # still there at t=2.8
    (closed,) = agg.pop_closed(now=3.0)
    assert closed.end_ts == 0.2
    (still_open,) = agg.flush()
    assert still_open.detection_count == 15


def test_long_track_is_emitted_before_it_ends():
    agg = StreamingAggregator(gap_seconds=1.0, max_event_seconds=5.0)
    agg.add([_det(t / 5) for t in range(30)])  # 0.0 .. 5.8 s, still going
    (event,) = agg.pop_closed(now=5.8)
    assert event.end_ts - event.start_ts >= 5.0
