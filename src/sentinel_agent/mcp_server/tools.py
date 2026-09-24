"""Tool logic as plain functions over a `Storage`, so it is unit-testable with no
MCP transport. `server.py` only wires these to `MCPServer` and adds schemas.

Expected failures (unknown id, bad cursor, inverted time range) raise
`ToolError`, whose text reaches the client verbatim. Anything else is a bug and
is masked by the server as a generic error.
"""

from collections import Counter
from datetime import UTC, datetime

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from sentinel_agent.agent.state import Action
from sentinel_agent.storage.base import (
    EventFilter,
    EventPage,
    EventRecord,
    InvalidCursorError,
    Storage,
    iso_utc,
)

MAX_PAGE = 100
MAX_SUMMARY_EVENTS = 5000


class EventSummary(BaseModel):
    total: int
    by_action: dict[str, int]
    by_label: dict[str, int]
    disagreements: int = Field(description="Events where detector and agent disagreed")
    first_occurred_at: str | None
    last_occurred_at: str | None
    alert_ids: list[str] = Field(description="Up to 20 most recent alert ids, for get_event")
    reviewed: int = Field(default=0, description="Events a person has given a verdict on")
    reviewed_real: int = 0
    reviewed_false_alarm: int = 0
    truncated: bool = Field(
        description=f"True if more than {MAX_SUMMARY_EVENTS} events matched; counts cover "
        "only the newest ones"
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    # LLMs often send timestamps without an offset; treat those as UTC rather than failing.
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _filters(
    camera_id: str | None, action: Action | None, since: datetime | None, until: datetime | None
) -> EventFilter:
    since, until = _as_utc(since), _as_utc(until)
    if since and until and since > until:
        raise ToolError(f"`since` ({since.isoformat()}) is after `until` ({until.isoformat()})")
    return EventFilter(camera_id=camera_id, action=action, since=since, until=until)


def list_events(
    storage: Storage,
    *,
    camera_id: str | None = None,
    action: Action | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> EventPage:
    filters = _filters(camera_id, action, since, until)
    try:
        return storage.query(filters, limit=min(limit, MAX_PAGE), cursor=cursor)
    except InvalidCursorError as exc:
        raise ToolError(f"{exc}. Use the next_cursor from a previous list_events call.") from exc


def get_event(storage: Storage, event_id: str) -> EventRecord:
    record = storage.get(event_id)
    if record is None:
        raise ToolError(f"No event with id {event_id!r}. Use list_events to find ids.")
    return record


def summarize_events(
    storage: Storage,
    *,
    camera_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> EventSummary:
    filters = _filters(camera_id, None, since, until)
    records: list[EventRecord] = []
    cursor = None
    while len(records) < MAX_SUMMARY_EVENTS:
        page = storage.query(filters, limit=MAX_PAGE, cursor=cursor)
        records += page.events
        cursor = page.next_cursor
        if cursor is None:
            break
    truncated = cursor is not None
    records = records[:MAX_SUMMARY_EVENTS]

    times = sorted(r.occurred_at for r in records)
    return EventSummary(
        total=len(records),
        by_action=dict(Counter(r.action for r in records).most_common()),
        by_label=dict(Counter(r.label for r in records).most_common()),
        disagreements=sum(r.disagreement for r in records),
        first_occurred_at=iso_utc(times[0]) if times else None,
        last_occurred_at=iso_utc(times[-1]) if times else None,
        alert_ids=[r.id for r in records if r.action == "alert"][:20],
        reviewed=sum(r.review is not None for r in records),
        reviewed_real=sum(r.review == "real" for r in records),
        reviewed_false_alarm=sum(r.review == "false_alarm" for r in records),
        truncated=truncated,
    )
