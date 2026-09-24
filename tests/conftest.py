import pytest

from sentinel_agent.events.models import Event


@pytest.fixture
def make_event():
    def _make(**overrides) -> Event:
        fields = {
            "id": "evt-1",
            "camera_id": "cam-01",
            "label": "person",
            "start_ts": 0.0,
            "end_ts": 4.0,
            "detection_count": 20,
            "max_raw_confidence": 0.93,
            "mean_raw_confidence": 0.91,
            "entered_restricted_zone": True,
        }
        return Event(**(fields | overrides))

    return _make
