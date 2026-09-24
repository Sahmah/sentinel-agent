from pydantic import BaseModel, Field


class Detection(BaseModel):
    """A single per-frame detection produced by a Detector."""

    camera_id: str
    frame_index: int
    timestamp: float = Field(description="Seconds since the start of the stream")
    label: str
    bbox: tuple[int, int, int, int] = Field(description="x, y, width, height in pixels")
    raw_confidence: float = Field(ge=0.0, le=1.0)
    in_restricted_zone: bool = False
    track_id: int | None = Field(
        default=None,
        description="Tracker identity, stable across frames; None without a tracker.",
    )
    is_true_positive: bool | None = Field(
        default=None,
        description="Known ground truth, only populated for synthetic/labeled scenarios.",
    )
