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


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Commands that save events must never write sentinel.db or snapshots/ into the repo."""
    monkeypatch.delenv("SENTINEL_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "sentinel.db"))
    monkeypatch.setenv("SENTINEL_SNAPSHOT_DIR", str(tmp_path / "snapshots"))


@pytest.fixture
def make_record():
    from datetime import UTC, datetime, timedelta

    from sentinel_agent.storage.base import EventRecord

    base = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    def _make(minute: int = 0, **overrides) -> EventRecord:
        fields = {
            "id": f"evt-{minute:03d}",
            "run_id": "run-1",
            "source": "demo",
            "camera_id": "cam-01",
            "label": "person",
            "occurred_at": base + timedelta(minutes=minute),
            "duration_seconds": 4.0,
            "detection_count": 20,
            "entered_restricted_zone": True,
            "p_cv": 0.84,
            "p_cv_calibrated": True,
            "llm_confidence": 0.9,
            "combined_confidence": 0.87,
            "disagreement": False,
            "severity": "high",
            "action": "alert",
            "reasoning": "Person entered the restricted zone.",
            "confidence_basis": "A reflection would lower confidence.",
            "triage_reason": "person detection",
            "is_true_positive": True,
        }
        return EventRecord(**(fields | overrides))

    return _make
