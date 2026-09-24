from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class Event(BaseModel):
    """A temporally-clustered group of detections — what the agent reasons about,
    not individual frames."""

    id: str
    camera_id: str
    label: str
    start_ts: float
    end_ts: float
    detection_count: int
    max_raw_confidence: float = Field(ge=0.0, le=1.0)
    mean_raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    entered_restricted_zone: bool = False
    is_true_positive: bool | None = Field(
        default=None,
        description="Majority ground truth of the member detections, synthetic runs only.",
    )
    best_frame_index: int | None = Field(
        default=None, description="Frame of the highest-confidence detection (for snapshots)"
    )
    best_bbox: tuple[int, int, int, int] | None = Field(
        default=None, description="That detection's box, x, y, w, h in pixels"
    )


class IncidentSummary(BaseModel):
    """The reasoning agent's output for one event."""

    event_id: str
    reasoning: str
    severity: Severity
    llm_confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: str


class Alert(BaseModel):
    event_id: str
    severity: Severity
    combined_confidence: float = Field(ge=0.0, le=1.0)
    disagreement: bool
    summary: str
