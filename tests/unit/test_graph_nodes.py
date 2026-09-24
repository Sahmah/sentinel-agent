import pytest
from botocore.exceptions import ClientError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END

from sentinel_agent.agent.graph import (
    DecisionPolicy,
    build_graph,
    make_decide_node,
    make_reason_node,
    route_after_triage,
    triage,
)
from sentinel_agent.agent.heuristic import heuristic_reasoning
from sentinel_agent.agent.llm import (
    DemoChatModel,
    ReasoningParseError,
    build_llm,
    invoke_with_backoff,
    parse_reasoning,
)
from sentinel_agent.agent.prompts import build_messages, event_payload

GOOD_REPLY = (
    '{"severity": "high", "reasoning": "Sustained track in zone.", "confidence": 0.8, '
    '"confidence_basis": "A reflection would change my mind."}'
)


def _fake(*replies: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter(AIMessage(content=r) for r in replies))


def _no_sleep(_: float) -> None:
    pass


# --- prompts / parsing -------------------------------------------------------


def test_prompt_hides_detector_confidence_and_ground_truth(make_event):
    text = build_messages(make_event(is_true_positive=True))[-1].text
    assert "raw_confidence" not in text
    assert "is_true_positive" not in text
    assert '"detection_count": 20' in text


def test_parse_tolerates_fences_and_percent_scale():
    out = parse_reasoning("Here:\n```json\n" + GOOD_REPLY.replace("0.8", "80") + "\n```")
    assert out.severity == "high"
    assert out.confidence == pytest.approx(0.8)


@pytest.mark.parametrize(
    "reply",
    ["no json here", "{not json}", '{"severity": "extreme", "reasoning": "x", "confidence": 0.5}'],
)
def test_parse_rejects_bad_replies(reply):
    with pytest.raises(ReasoningParseError):
        parse_reasoning(reply)


# --- llm construction / retries ----------------------------------------------


def test_build_llm_defaults_to_demo(monkeypatch):
    monkeypatch.delenv("SENTINEL_LLM_BACKEND", raising=False)
    assert isinstance(build_llm(), DemoChatModel)
    with pytest.raises(ValueError):
        build_llm("openai")


def test_demo_model_answers_with_heuristic(make_event):
    event = make_event(detection_count=1, end_ts=0.0)
    reply = DemoChatModel().invoke(build_messages(event))
    expected = heuristic_reasoning(event_payload(event))
    assert parse_reasoning(reply.text) == expected


def _throttle() -> ClientError:
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")


class _FlakyModel:
    def __init__(self, failures: list[Exception]):
        self.failures = failures
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return AIMessage(content=GOOD_REPLY)


def test_backoff_retries_throttling_then_succeeds():
    model, sleeps = _FlakyModel([_throttle(), _throttle()]), []
    reply = invoke_with_backoff(model, [], sleep=sleeps.append)
    assert reply.text == GOOD_REPLY
    assert model.calls == 3
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1]


def test_backoff_does_not_retry_other_errors():
    model = _FlakyModel([ValueError("bad request")])
    with pytest.raises(ValueError):
        invoke_with_backoff(model, [], sleep=_no_sleep)
    assert model.calls == 1


def test_backoff_gives_up_after_max_attempts():
    model = _FlakyModel([_throttle() for _ in range(3)])
    with pytest.raises(ClientError):
        invoke_with_backoff(model, [], max_attempts=3, sleep=_no_sleep)


# --- nodes -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "in_zone", "passed"),
    [("person", False, True), ("object", True, True), ("object", False, False)],
)
def test_triage(make_event, label, in_zone, passed):
    update = triage(
        {"event": make_event(label=label, entered_restricted_zone=in_zone).model_dump()}
    )
    assert update["triage_passed"] is passed
    assert update["severity"] is None  # downstream fields are always reset
    assert route_after_triage(update) == ("reason" if passed else END)
    if not passed:
        assert update["action"] == "dismissed"


@pytest.mark.parametrize(
    ("count", "in_zone", "passed"),
    [(1, False, False), (2, False, False), (3, False, True), (1, True, True)],
)
def test_triage_min_person_detections_only_applies_outside_zone(make_event, count, in_zone, passed):
    event = make_event(detection_count=count, entered_restricted_zone=in_zone)
    update = triage({"event": event.model_dump()}, min_person_detections_outside_zone=3)
    assert update["triage_passed"] is passed


def test_policy_min_detections_reaches_the_graph(make_event):
    graph = build_graph(
        _fake(GOOD_REPLY), policy=DecisionPolicy(min_person_detections_outside_zone=3)
    )
    event = make_event(detection_count=1, entered_restricted_zone=False)
    state = graph.invoke({"event": event.model_dump(), "p_cv": 0.9})
    assert state["action"] == "dismissed"
    assert state["llm_confidence"] is None  # the LLM was never called


def test_reason_node_maps_reply_to_state(make_event):
    update = make_reason_node(_fake(GOOD_REPLY))({"event": make_event().model_dump()})
    assert update["severity"] == "high"
    assert update["llm_confidence"] == 0.8
    assert update["reasoning_failed"] is False


def test_reason_node_retries_with_feedback_once(make_event):
    update = make_reason_node(_fake("garbage", GOOD_REPLY))({"event": make_event().model_dump()})
    assert update["severity"] == "high"


def test_reason_node_gives_up_without_guessing(make_event):
    update = make_reason_node(_fake("garbage", "still garbage"))(
        {"event": make_event().model_dump()}
    )
    assert update["reasoning_failed"] is True
    assert "severity" not in update


@pytest.mark.parametrize(
    ("p_cv", "p_llm", "severity", "action"),
    [
        (0.95, 0.9, "high", "alert"),
        (0.95, 0.9, "low", "logged"),
        (0.05, 0.1, "medium", "dismissed"),
        (0.5, 0.5, "high", "human_review"),  # agree, but not confident enough
        (0.98, 0.2, "medium", "human_review"),  # detector sure, agent not: disagreement
    ],
)
def test_decide(p_cv, p_llm, severity, action):
    decide = make_decide_node(DecisionPolicy())
    update = decide({"p_cv": p_cv, "llm_confidence": p_llm, "severity": severity})
    assert update["action"] == action


def test_decide_sends_failed_reasoning_to_a_human():
    update = make_decide_node(DecisionPolicy())({"p_cv": 0.99, "reasoning_failed": True})
    assert update["action"] == "human_review"


_PAYLOAD = {
    "label": "person",
    "duration_seconds": 0.0,
    "detection_count": 1,
    "entered_restricted_zone": True,
}


def test_heuristic_confidence_tracks_persistence():
    def conf(n: int) -> float:
        payload = {**_PAYLOAD, "detection_count": n, "duration_seconds": n / 5}
        return heuristic_reasoning(payload).confidence

    assert conf(1) < conf(3) < conf(6) < conf(30)
    outside = {**_PAYLOAD, "label": "object", "entered_restricted_zone": False}
    assert heuristic_reasoning(outside).severity == "low"
