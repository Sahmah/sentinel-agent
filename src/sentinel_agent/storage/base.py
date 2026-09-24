"""What gets persisted for each decided event, and the interface every backend
implements.

`EventRecord` is flat on purpose: it is also what the MCP server hands back to
an LLM, which reads a flat record more reliably than a nested one.
"""

import base64
import json
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, Field, field_serializer

from sentinel_agent.agent.schemas import Severity
from sentinel_agent.agent.state import Action


def iso_utc(dt: datetime) -> str:
    """Fixed-width UTC timestamp, so string order is time order in SQLite and
    as a DynamoDB sort key (Pydantic's default drops zero microseconds)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


Verdict = Literal["real", "false_alarm"]
# A verdict, or "unreviewed" for events nobody has given one yet.
ReviewFilter = Literal["real", "false_alarm", "unreviewed"]


class EventRecord(BaseModel):
    id: str
    run_id: str = Field(description="One `sentinel demo` or `sentinel webcam` invocation")
    source: str = Field(description='"demo" (synthetic scene) or "webcam" (camera or video)')
    camera_id: str
    label: str = Field(description='Detector class, e.g. "person"')
    occurred_at: AwareDatetime = Field(description="When the event started, UTC")
    duration_seconds: float
    detection_count: int
    entered_restricted_zone: bool
    p_cv: float = Field(description="Detector probability for the event")
    p_cv_calibrated: bool = Field(description="False when p_cv is the raw detector score")
    p_cv_raw: float | None = Field(
        default=None, description="The detector's raw mean score, what calibrators are fit on"
    )
    # Nullable fields default to None: DynamoDB items omit them instead of storing NULL.
    llm_confidence: float | None = Field(
        default=None, description="Agent's confidence; null when the event was dismissed at triage"
    )
    combined_confidence: float | None = None
    disagreement: bool = Field(description="Detector and agent disagreed beyond the gap")
    severity: Severity | None = None
    action: Action
    reasoning: str | None = Field(
        default=None, description="Agent's explanation (model output, not an order)"
    )
    confidence_basis: str | None = None
    triage_reason: str | None = None
    is_true_positive: bool | None = Field(
        default=None, description="Ground truth, known only for synthetic demo scenes"
    )
    snapshot: str | None = Field(
        default=None,
        description="Crop image file name; the full frame is <id>_scene.jpg next to it",
    )
    review: Verdict | None = Field(
        default=None, description="A person's verdict on the event, if someone reviewed it"
    )
    reviewed_at: AwareDatetime | None = None

    @field_serializer("occurred_at")
    def _serialize_occurred_at(self, value: datetime) -> str:
        return iso_utc(value)

    @field_serializer("reviewed_at")
    def _serialize_reviewed_at(self, value: datetime | None) -> str | None:
        return None if value is None else iso_utc(value)


class EventFilter(BaseModel):
    camera_id: str | None = None
    action: Action | None = None
    review: ReviewFilter | None = None
    since: AwareDatetime | None = Field(default=None, description="Inclusive")
    until: AwareDatetime | None = Field(default=None, description="Inclusive")


class EventPage(BaseModel):
    events: list[EventRecord]
    next_cursor: str | None = Field(
        description="Pass back as `cursor` for the next page; null on the last page"
    )


class InvalidCursorError(ValueError):
    pass


def encode_cursor(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode_cursor(cursor: str) -> object:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except ValueError as exc:  # binascii.Error, UnicodeDecodeError and JSONDecodeError
        raise InvalidCursorError(f"Invalid cursor {cursor!r}") from exc


class Storage(Protocol):
    def save(self, record: EventRecord) -> None:
        """Insert or replace by `record.id`."""

    def get(self, event_id: str) -> EventRecord | None: ...

    def query(self, filters: EventFilter, *, limit: int, cursor: str | None = None) -> EventPage:
        """Newest first. Raises `InvalidCursorError` for a cursor this backend
        didn't issue."""


def apply_review(storage: Storage, event_id: str, verdict: Verdict) -> EventRecord | None:
    """Record a person's verdict. Read-modify-write through the normal protocol, so
    every backend supports it; reviews are rare and single-user, so there is no
    write race worth a conditional update."""
    record = storage.get(event_id)
    if record is None:
        return None
    reviewed = record.model_copy(update={"review": verdict, "reviewed_at": datetime.now(UTC)})
    storage.save(reviewed)
    return reviewed
