"""triage -> reason -> decide, as a LangGraph state graph.

- `triage` is a cheap deterministic filter: events that can't matter (a
  non-person object outside the restricted zone, or, if the policy asks for it,
  a person flickering for too few frames outside the zone) never cost an LLM call.
- `reason` makes one LLM call and parses its JSON reply, re-asking once with
  the parse error as feedback before giving up. A reply that still can't be
  parsed routes the event to a human instead of guessing.
- `decide` fuses the calibrated detector probability with the LLM's confidence
  (`calibration.fusion`) and picks an action.

The LLM is injected (`build_graph(llm)`), so tests and demo mode swap in a fake
or local model without touching the nodes.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from sentinel_agent.agent.llm import ReasoningParseError, invoke_with_backoff, parse_reasoning
from sentinel_agent.agent.prompts import build_messages
from sentinel_agent.agent.state import Action, EventState
from sentinel_agent.calibration.fusion import should_escalate
from sentinel_agent.events.models import Event
from sentinel_agent.memory import ReviewMemory


@dataclass(frozen=True)
class DecisionPolicy:
    """Thresholds for `triage` and `decide`. `threshold`, `disagreement_gap` and
    `w_cv` are passed straight to `fusion.should_escalate`; `dismiss_below` is
    the extra step that keeps agreed-upon noise from flooding the human review
    queue. `min_person_detections_outside_zone` does the same one step earlier:
    on live video, a person seen in a single frame outside the zone is almost
    always a detector flicker, and would otherwise land in human review because
    the detector (high per-frame score) and the agent (short track) disagree."""

    w_cv: float = 0.5
    threshold: float = 0.6
    disagreement_gap: float = 0.35
    dismiss_below: float = 0.3
    min_person_detections_outside_zone: int = 1


def triage(state: EventState, *, min_person_detections_outside_zone: int = 1) -> dict:
    event = Event.model_validate(state["event"])
    if event.entered_restricted_zone:
        passed = True
        reason = (
            "person detection" if event.label == "person" else ("object inside the restricted zone")
        )
    elif event.label != "person":
        passed, reason = False, "non-person object outside the restricted zone"
    elif event.detection_count < min_person_detections_outside_zone:
        passed = False
        reason = (
            f"person outside the restricted zone seen in only {event.detection_count} "
            f"frame(s), below {min_person_detections_outside_zone}"
        )
    else:
        passed, reason = True, "person detection"
    update: dict = {
        "triage_passed": passed,
        "triage_reason": reason,
        # Reset everything downstream: with a per-camera checkpointer thread, the
        # previous event's results would otherwise leak into this one.
        "severity": None,
        "reasoning": None,
        "llm_confidence": None,
        "confidence_basis": None,
        "reasoning_failed": False,
        "combined_confidence": None,
        "disagreement": False,
    }
    if not passed:
        update["action"] = "dismissed"
    return update


def route_after_triage(state: EventState) -> str:
    return "reason" if state["triage_passed"] else END


def make_reason_node(
    llm: BaseChatModel,
    *,
    max_parse_attempts: int = 2,
    sleep: Callable[[float], None] = time.sleep,
    vision: bool = False,
    memory: ReviewMemory | None = None,
    max_example_images: int = 2,
) -> Callable[[EventState], dict]:
    def reason(state: EventState) -> dict:
        event = Event.model_validate(state["event"])
        image = _read_snapshot(state.get("snapshot_path")) if vision else None
        examples = []
        for i, example in enumerate(memory.examples_for(event) if memory else []):
            # Each image costs model time; only the closest examples get theirs.
            with_image = vision and i < max_example_images
            examples.append((example, _read_snapshot(example.image_path) if with_image else None))
        feedback: str | None = None
        for _ in range(max_parse_attempts):
            messages = build_messages(event, feedback=feedback, image=image, examples=examples)
            reply = invoke_with_backoff(llm, messages, sleep=sleep)
            try:
                out = parse_reasoning(reply.text)
            except ReasoningParseError as exc:
                feedback = str(exc)
                continue
            return {
                "severity": out.severity,
                "reasoning": out.reasoning,
                "llm_confidence": out.confidence,
                "confidence_basis": out.confidence_basis,
                "reasoning_failed": False,
            }
        return {
            "reasoning": f"LLM reply could not be parsed after {max_parse_attempts} attempts: "
            f"{feedback}",
            "reasoning_failed": True,
        }

    return reason


def _read_snapshot(path: str | None) -> bytes | None:
    # A missing crop (no frame kept, disk full) degrades to a text-only prompt.
    if not path:
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def make_decide_node(policy: DecisionPolicy) -> Callable[[EventState], dict]:
    def decide(state: EventState) -> dict:
        if state.get("reasoning_failed") or state.get("llm_confidence") is None:
            return {"action": "human_review", "combined_confidence": None, "disagreement": False}

        fusion = should_escalate(
            state["p_cv"],
            state["llm_confidence"],
            w_cv=policy.w_cv,
            threshold=policy.threshold,
            disagreement_gap=policy.disagreement_gap,
        )
        action: Action
        if fusion.disagreement:
            action = "human_review"
        elif fusion.combined_confidence < policy.dismiss_below:
            action = "dismissed"
        elif fusion.should_escalate:
            action = "human_review"
        elif state["severity"] in ("high", "critical"):
            action = "alert"
        else:
            action = "logged"
        return {
            "action": action,
            "combined_confidence": fusion.combined_confidence,
            "disagreement": fusion.disagreement,
        }

    return decide


def build_graph(
    llm: BaseChatModel,
    *,
    checkpointer: Checkpointer = None,
    policy: DecisionPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    vision: bool = False,
    memory: ReviewMemory | None = None,
):
    """`vision=True` attaches each event's snapshot to the reasoning prompt; the
    model must accept images (e.g. gemma3 on Ollama, Claude on Bedrock).
    `memory` adds similar events a person already reviewed (see memory.py)."""
    policy = policy or DecisionPolicy()
    builder = StateGraph(EventState)
    builder.add_node(
        "triage",
        partial(
            triage, min_person_detections_outside_zone=policy.min_person_detections_outside_zone
        ),
    )
    builder.add_node("reason", make_reason_node(llm, sleep=sleep, vision=vision, memory=memory))
    builder.add_node("decide", make_decide_node(policy))
    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", route_after_triage, {"reason": "reason", END: END})
    builder.add_edge("reason", "decide")
    builder.add_edge("decide", END)
    return builder.compile(checkpointer=checkpointer)
