from datetime import datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from sentinel_agent.mcp_server import tools
from sentinel_agent.storage.sqlite_store import SqliteStorage


@pytest.fixture
def store(tmp_path, make_record):
    store = SqliteStorage(tmp_path / "events.db")
    for minute, (label, action, disagreement) in enumerate(
        [
            ("person", "alert", False),
            ("person", "human_review", True),
            ("object", "dismissed", False),
            ("person", "logged", False),
        ]
    ):
        store.save(make_record(minute, label=label, action=action, disagreement=disagreement))
    return store


def test_get_event_unknown_id_is_a_tool_error(store):
    with pytest.raises(ToolError, match="list_events"):
        tools.get_event(store, "nope")


def test_naive_timestamps_are_read_as_utc(store):
    page = tools.list_events(store, since=datetime(2026, 9, 24, 12, 2))
    assert [r.id for r in page.events] == ["evt-003", "evt-002"]


def test_inverted_range_and_bad_cursor_are_tool_errors(store):
    with pytest.raises(ToolError, match="after"):
        tools.list_events(store, since=datetime(2026, 9, 25), until=datetime(2026, 9, 24))
    with pytest.raises(ToolError, match="next_cursor"):
        tools.list_events(store, cursor="garbage")


def test_limit_is_capped(store, monkeypatch):
    monkeypatch.setattr(tools, "MAX_PAGE", 2)
    assert len(tools.list_events(store, limit=50).events) == 2


def test_summary_counts(store):
    s = tools.summarize_events(store)
    assert s.total == 4
    assert s.by_action == {"alert": 1, "human_review": 1, "dismissed": 1, "logged": 1}
    assert s.by_label == {"person": 3, "object": 1}
    assert s.disagreements == 1
    assert s.alert_ids == ["evt-000"]
    assert s.first_occurred_at < s.last_occurred_at
    assert not s.truncated


def test_summary_pages_through_and_flags_truncation(store, monkeypatch):
    monkeypatch.setattr(tools, "MAX_PAGE", 1)  # force several storage pages
    assert tools.summarize_events(store).total == 4
    monkeypatch.setattr(tools, "MAX_SUMMARY_EVENTS", 3)
    s = tools.summarize_events(store)
    assert (s.total, s.truncated) == (3, True)


def test_empty_store_summary(tmp_path):
    s = tools.summarize_events(SqliteStorage(tmp_path / "empty.db"))
    assert (s.total, s.first_occurred_at, s.alert_ids) == (0, None, [])
