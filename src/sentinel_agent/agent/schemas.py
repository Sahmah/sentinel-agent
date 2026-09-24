from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class ReasoningOutput(BaseModel):
    """The structured output we ask the reasoning LLM for."""

    severity: Severity
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: str
