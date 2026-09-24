from hypothesis import given
from hypothesis import strategies as st

from sentinel_agent.detection.models import Detection
from sentinel_agent.events.aggregator import cluster_into_events


def _det(t: float, x: int = 100, label: str = "person", tp: bool | None = None) -> Detection:
    return Detection(
        camera_id="cam",
        frame_index=int(t * 5),
        timestamp=t,
        label=label,
        bbox=(x, 100, 10, 10),
        raw_confidence=0.9,
        is_true_positive=tp,
    )


def test_time_gap_splits_events():
    events = cluster_into_events([_det(0.0), _det(0.2), _det(5.0)], gap_seconds=1.0)
    assert [e.detection_count for e in events] == [2, 1]


def test_distant_objects_with_same_label_stay_separate():
    detections = [_det(t / 5, x=20) for t in range(5)] + [_det(t / 5, x=250) for t in range(5)]
    events = cluster_into_events(detections)
    assert len(events) == 2
    assert all(e.detection_count == 5 for e in events)


def test_labels_are_never_mixed():
    events = cluster_into_events([_det(0.0, label="person"), _det(0.2, label="object")])
    assert sorted(e.label for e in events) == ["object", "person"]


def test_ground_truth_is_majority_vote():
    event = cluster_into_events([_det(0.0, tp=True), _det(0.2, tp=True), _det(0.4, tp=False)])[0]
    assert event.is_true_positive is True
    assert cluster_into_events([_det(0.0)])[0].is_true_positive is None


hits = st.lists(
    st.tuples(
        st.floats(0, 60, allow_nan=False),
        st.integers(0, 300),
        st.sampled_from(["person", "object"]),
    ),
    max_size=80,
)


@given(hits)
def test_no_detection_is_lost(frame_hits):
    detections = [_det(t, x=x, label=label) for t, x, label in frame_hits]
    events = cluster_into_events(detections)
    assert sum(e.detection_count for e in events) == len(detections)


@given(hits)
def test_events_are_sorted_and_well_formed(frame_hits):
    events = cluster_into_events([_det(t, x=x, label=label) for t, x, label in frame_hits])
    assert [e.start_ts for e in events] == sorted(e.start_ts for e in events)
    assert all(e.start_ts <= e.end_ts for e in events)
    assert all(e.mean_raw_confidence <= e.max_raw_confidence for e in events)
