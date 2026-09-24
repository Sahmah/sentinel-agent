"""Deterministic, rule-based stand-in for the reasoning LLM.

Used by demo mode so `sentinel demo` runs end-to-end at zero cost with no AWS
credentials. It answers the same question the LLM is asked (see `prompts.py`)
from the same event fields, so the rest of the pipeline — parsing, fusion,
escalation — is exercised exactly as it would be with Bedrock.

It is deliberately simple and is not meant to be "smart": its job is to be a
transparent, reproducible second opinion whose confidence depends on evidence
the detector's per-frame score does not see (how long the track lasted).
"""

from sentinel_agent.agent.schemas import ReasoningOutput, Severity

SUSTAINED_TRACK_DETECTIONS = 10
SHORT_TRACK_DETECTIONS = 4


def heuristic_reasoning(payload: dict) -> ReasoningOutput:
    """`payload` is exactly what the LLM is shown (`prompts.event_payload`), so
    the heuristic has no access to anything the real model wouldn't see."""
    duration = payload["duration_seconds"]
    n = payload["detection_count"]
    label = payload["label"]
    in_zone = payload["entered_restricted_zone"]

    # Confidence that this is a genuine target rather than a detector artifact.
    # A real object persists across frames; clutter and noise flicker.
    if n >= SUSTAINED_TRACK_DETECTIONS:
        confidence, track = 0.9, f"sustained track ({n} detections over {duration:.1f}s)"
    elif n >= SHORT_TRACK_DETECTIONS:
        confidence, track = 0.65, f"short track ({n} detections over {duration:.1f}s)"
    elif n >= 2:
        confidence, track = 0.35, f"brief flicker ({n} detections over {duration:.1f}s)"
    else:
        confidence, track = 0.2, "single-frame detection"
    if label != "person":
        confidence = round(confidence * 0.8, 2)

    severity: Severity
    if label == "person" and in_zone:
        severity = "high" if n >= SUSTAINED_TRACK_DETECTIONS else "medium"
        where = "entered the restricted zone"
    elif in_zone:
        severity, where = "medium", "appeared in the restricted zone (not classified as a person)"
    else:
        severity, where = "low", "stayed outside the restricted zone"

    reasoning = f"{label.capitalize()} {where}; {track}."
    basis = (
        "A longer continuous track would raise confidence; a track this short is "
        "consistent with clutter."
        if confidence < 0.5
        else "Evidence the track is a reflection or static clutter would lower confidence."
    )
    return ReasoningOutput(
        severity=severity, reasoning=reasoning, confidence=confidence, confidence_basis=basis
    )
