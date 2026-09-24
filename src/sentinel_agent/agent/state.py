from typing import Literal

from typing_extensions import TypedDict

from sentinel_agent.agent.schemas import Severity

Action = Literal["dismissed", "logged", "human_review", "alert"]


class EventState(TypedDict, total=False):
    """Graph state for one event. Changing this shape breaks resumption of
    existing checkpoints — version it deliberately (langgraph-bedrock skill, §4).

    Inputs: `event` (an `Event` dumped to a dict) and `p_cv` (the calibrated
    detector probability). Everything else is written by the nodes.
    """

    event: dict
    p_cv: float

    triage_passed: bool
    triage_reason: str

    severity: Severity | None
    reasoning: str | None
    llm_confidence: float | None
    confidence_basis: str | None
    reasoning_failed: bool

    combined_confidence: float | None
    disagreement: bool
    action: Action
