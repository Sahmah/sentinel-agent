"""Combine a calibrated CV confidence and an LLM certainty signal into one
escalate/don't-escalate decision.

Scope note: this treats the two signals as independent evidence and combines
them with a simple weighted average plus a disagreement check. That is a
deliberately simplified, honest approach — real multi-agent uncertainty
research (trajectory-adapted UQ, counterfactual-graph calibration; see the
confidence-calibration skill, section 3, for citations) goes further by
modeling correlated failures across communicating agents. Sentinel Agent has
one detector and one reasoning agent, not a communicating swarm, so the
independence assumption is a smaller stretch here — but it is still an
assumption, not a proven property.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FusionResult:
    combined_confidence: float
    disagreement: bool
    should_escalate: bool


def combined_confidence(p_cv: float, p_llm: float, *, w_cv: float = 0.5) -> float:
    """Weighted linear combination. `w_cv` is a tunable prior on which signal
    you trust more; start at 0.5 and adjust from escalation-review outcomes."""
    return w_cv * p_cv + (1 - w_cv) * p_llm


def should_escalate(
    p_cv: float,
    p_llm: float,
    *,
    w_cv: float = 0.5,
    threshold: float = 0.6,
    disagreement_gap: float = 0.35,
) -> FusionResult:
    """Escalate to a human when combined confidence is low OR the two signals
    strongly disagree. Disagreement is informative on its own: it means the
    detector and the reasoning agent aren't corroborating each other, which
    should route to a human even if each score individually looks fine — the
    independent-evidence assumption is likely breaking down for this event.
    """
    combined = combined_confidence(p_cv, p_llm, w_cv=w_cv)
    disagree = abs(p_cv - p_llm) > disagreement_gap
    return FusionResult(
        combined_confidence=combined,
        disagreement=disagree,
        should_escalate=combined < threshold or disagree,
    )
