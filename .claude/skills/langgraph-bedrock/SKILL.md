---
name: langgraph-bedrock
description: Production patterns for LangGraph multi-agent pipelines using AWS Bedrock (Claude) as the LLM backend, used in the Sentinel Agent project
---

# LangGraph + Bedrock: Production Patterns for Sentinel Agent

Patterns for a CV-event -> triage -> reason -> decide pipeline, orchestrated with LangGraph, backed by Claude on Bedrock via `langchain-aws`. Assumes familiarity with LangGraph/Bedrock basics — this skips 101 content.

## 1. Graph structure: triage -> reason -> decide

**State schema.** Use `TypedDict` (the documented default — simplest, fastest, no validation overhead) unless you need runtime validation of untrusted input, in which case use a Pydantic `BaseModel` state (supported, but slower). Keep state minimal and typed; don't stuff transient scratch values into it — pass those through function args instead. [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)

```python
from typing_extensions import TypedDict
from typing import Literal
from langgraph.graph import StateGraph, START, END


class EventState(TypedDict):
    raw_event: dict  # detector output (bbox, class, frame_ref, det_confidence)
    triage_result: dict | None  # cheap pre-filter output
    reasoning: str | None  # Claude's analysis
    severity: Literal["low", "medium", "high", "critical"] | None
    confidence: float | None  # see §5
    should_alert: bool | None
```

**Nodes do work, edges route.** Keep each node a single, pure-ish responsibility (triage, reason, decide) so it's unit-testable in isolation without spinning up the graph. Put branching logic in a dedicated routing function, not inline in a node — a typo in a conditional's return string silently misroutes with no error.

```python
def triage(state: EventState) -> dict:
    # cheap, deterministic filter — no LLM call. Returns partial state update.
    ...


def reason(state: EventState) -> dict:
    # single Bedrock call, returns {"reasoning": ..., "severity": ..., "confidence": ...}
    ...


def decide(state: EventState) -> dict:
    return {"should_alert": state["severity"] in ("high", "critical")}


def route_after_triage(state: EventState) -> str:
    return "reason" if state["triage_result"]["passed"] else END


builder = StateGraph(EventState)
builder.add_node("triage", triage)
builder.add_node("reason", reason)
builder.add_node("decide", decide)
builder.add_edge(START, "triage")
builder.add_conditional_edges("triage", route_after_triage, {"reason": "reason", END: END})
builder.add_edge("reason", "decide")
builder.add_edge("decide", END)
graph = builder.compile()  # must compile before invoking
```

Each node takes `(state)`, or optionally `(state, config)` / `(state, config, runtime)` for injected dependencies (checkpointer store, config, thread-scoped context) — see §3. [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)

**Recursion limits.** If any edge routes back for retry (e.g. re-reason on parse failure), set `recursion_limit` explicitly below the default 25 — an unbounded retry loop on a broken parser will burn Bedrock quota fast.

## 2. Bedrock integration via langchain-aws

**Use `ChatBedrockConverse`, not `ChatBedrock`.** `ChatBedrockConverse` targets AWS's standardized Converse API, has native tool-use/structured-output support, and is where new Bedrock features land first; `ChatBedrock` targets the older `InvokeModel` path and is being phased toward Converse feature parity. Only fall back to `ChatBedrock` if you need a custom/fine-tuned Bedrock model that Converse doesn't yet support. [langchain-aws issue #349](https://github.com/langchain-ai/langchain-aws/issues/349), [ChatBedrock docs](https://docs.langchain.com/oss/python/integrations/chat/bedrock)

```python
from langchain_aws import ChatBedrockConverse

llm = ChatBedrockConverse(
    model="anthropic.claude-sonnet-4-6-v1:0",  # Bedrock model id, not the Anthropic-API id
    region_name="us-east-1",
    temperature=0,
    max_tokens=1024,
)
```

**Structured output / tool calling.** `with_structured_output()` on `ChatBedrockConverse` works by wrapping your schema as a forced tool call under the hood — not (yet) via a native constrained-decoding endpoint for most models. Native structured-output constraints exist on Bedrock for a subset of Claude models (Haiku 4.5, Sonnet 4.5, Opus 4.5/4.6) but aren't the default path through `with_structured_output()`. [langchain-aws issue #883](https://github.com/langchain-ai/langchain-aws/issues/883), [AWS Bedrock structured outputs docs](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-structured-outputs.html)

```python
from pydantic import BaseModel, Field


class TriageDecision(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    reasoning: str
    confidence: float = Field(ge=0, le=1)


structured_llm = llm.with_structured_output(TriageDecision)
result: TriageDecision = structured_llm.invoke(prompt)
```

**Known pitfall — forced `tool_choice` rejected on newer Claude models.** `ChatBedrockConverse.with_structured_output()` defaults to sending a named `tool_choice`, which some newer Claude releases on Bedrock reject with a 400 (forced tool choice unsupported for that model). If you hit this, bind the tool with `tool_choice="auto"` plus an explicit system instruction naming the tool, and validate/parse the result yourself rather than relying on forced choice. [langchain-aws issue #1310](https://github.com/langchain-ai/langchain-aws/issues/1310)

## 3. Swappable / mock LLM backend (demo mode, DI)

Don't hardcode `ChatBedrockConverse(...)` inside node functions — inject it. This gets you a zero-AWS demo mode and fast tests for free. LangGraph's own DI mechanism is **runtime context** (the third `runtime` arg on a node, or `config["configurable"]`), which is the documented way to pass execution-scoped dependencies like clients into nodes without hardcoding them. [Runtime & DI reference](https://deepwiki.com/langchain-ai/langgraph/3.9-runtime-and-dependency-injection)

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_aws import ChatBedrockConverse
import os


def build_llm():
    if os.environ.get("SENTINEL_DEMO_MODE") == "1":
        return GenericFakeChatModel(
            messages=iter(
                [
                    AIMessage(
                        content='{"severity":"high","reasoning":"demo mode","confidence":0.9}'
                    ),
                ]
            )
        )
    return ChatBedrockConverse(model="anthropic.claude-sonnet-4-6-v1:0", region_name="us-east-1")


# Inject via closure/factory so nodes stay pure functions of (state, config):
def make_reason_node(llm):
    def reason(state: EventState) -> dict:
        structured = llm.with_structured_output(TriageDecision)
        out = structured.invoke(build_prompt(state))
        return {"reasoning": out.reasoning, "severity": out.severity, "confidence": out.confidence}

    return reason


builder.add_node("reason", make_reason_node(build_llm()))
```

Any `BaseChatModel`-compatible object (real `ChatBedrockConverse`, `GenericFakeChatModel`, `FakeListChatModel`, or a hand-rolled stub) can be swapped in this way because LangGraph nodes only need `.invoke`/`with_structured_output` on the object you close over — this is the same "Runnable" interface everywhere in the LangChain ecosystem, so no bespoke abstraction layer is needed.

## 4. State persistence / checkpointing

For a monitoring pipeline processing a *stream* of events over time (not one-shot chains), checkpointing buys you: resumability after a crash mid-run, replay/audit of what the agent decided per event, and human-in-the-loop interrupts. It costs you: storage growth, and (for Postgres/Sqlite) I/O latency per step.

- `InMemorySaver` (`langgraph.checkpoint.memory`) — dev/test only, lost on restart.
- `SqliteSaver` (`langgraph.checkpoint.sqlite`) — durable, single-process. Good fit for a demo/local Sentinel Agent deployment (one process watching a camera feed).
- `PostgresSaver` / `AsyncPostgresSaver` (`langgraph.checkpoint.postgres`) — for multi-process/horizontally-scaled deployments where more than one worker needs to read/write the same thread's state.

[Persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

with SqliteSaver.from_conn_string("sentinel_events.db") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke(
        {"raw_event": event},
        {"configurable": {"thread_id": event["camera_id"]}},  # one thread per camera/stream
    )
```

For Sentinel Agent specifically: use one `thread_id` per camera/sensor stream (not one per event) if you want the agent to see recent event history for that stream as context; use one `thread_id` per event if each event should be evaluated independently. Version your `EventState` TypedDict deliberately — adding/removing fields breaks resumption of existing checkpoints, since the checkpointer deserializes into the current schema.

## 5. Confidence / uncertainty handling — no ecosystem support, build it yourself

**There is no built-in LangChain/LangGraph primitive for confidence scores.** Neither library tracks or propagates uncertainty through a graph; you own this entirely as application state (the `confidence: float` field in `EventState` above is the whole mechanism). Be aware of what you're actually measuring: a verbalized confidence number from Claude is a generated token, not a calibrated internal probability — research explicitly flags that RLHF training rewards confident-sounding output over honestly hedged output, so verbalized confidence is not a substitute for calibration. [Evaluating LLM Confidence and Uncertainty (2026)](https://futureagi.com/blog/evaluating-llm-confidence-uncertainty-2026/)

Rigorous approaches (multi-sampling for variance, log-prob-based uncertainty, trajectory-level uncertainty propagation frameworks like SAUP) exist in current research but assume access to logprobs or repeated sampling — usually impractical/expensive against a black-box Bedrock Converse endpoint. [Uncertainty Propagation in LLM-Based Systems](https://arxiv.org/html/2604.23505v1)

Pragmatic pattern for this project: ask Claude to emit a `confidence` field alongside `severity`/`reasoning` in the structured-output schema (as above), treat it as a soft signal for the `decide` node's threshold (e.g. downgrade `should_alert` if `confidence < 0.5`), and — if you want a defensible eval later — log `(event, verbalized_confidence, human_label)` triples so you can measure calibration empirically rather than assume it. State clearly in the project writeup that this is a self-designed heuristic, not an established library feature.

## 6. Error handling and retries for Bedrock calls

Two distinct failure modes need separate handling:

**Throttling (`ThrottlingException` / 429s).** `ChatBedrockConverse` accepts `max_retries`, but the underlying boto3 Converse client has historically shipped a low hardcoded default and env vars like `AWS_BEDROCK_MAX_RETRIES` don't reliably reach it — verify the effective retry count rather than trusting the constructor default. [langchain-aws issue #819](https://github.com/langchain-ai/langchain-aws/issues/819)

```python
llm = ChatBedrockConverse(
    model="anthropic.claude-sonnet-4-6-v1:0",
    region_name="us-east-1",
    max_tokens=1024,
    config=Config(
        retries={"max_attempts": 10, "mode": "adaptive"}
    ),  # boto3 Config, belt-and-suspenders
)
```

Add your own exponential backoff with jitter around the node's LLM call as a second layer, since botocore retries don't cover every failure path (e.g. `ReadTimeoutError` on long Converse calls has been reported to bypass retry). [AWS: retry/backoff for Bedrock](https://repost.aws/knowledge-center/bedrock-retry-exponential-backoff-api)

```python
import random, time
from botocore.exceptions import ClientError


def invoke_with_backoff(structured_llm, prompt, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            return structured_llm.invoke(prompt)
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "ThrottlingException",
                "ServiceUnavailableException",
            ):
                raise
            if attempt == max_attempts - 1:
                raise
            time.sleep(min(60, (2**attempt) + random.uniform(0, 1)))
```

**Structured-output parse failures.** `with_structured_output()` raises when the forced tool call's arguments don't validate against your Pydantic schema (malformed JSON, missing field). Treat this as retryable-with-feedback: on failure, re-invoke with the validation error appended to the prompt so Claude can self-correct, capped at 2-3 attempts, then fail the event to a dead-letter/manual-review state rather than looping silently (see recursion-limit note in §1).

## 7. Testing strategy

Two levels: unit-test nodes as plain functions (no graph, no framework), and integration-test full graph runs with a fake LLM swapped in via §3's injection point. Never let real Bedrock calls into CI — they're slow, cost money, and rate-limit shared dev credentials.

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


def test_reason_node_maps_high_severity_to_alert():
    fake_llm = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content='{"severity":"critical","reasoning":"weapon detected","confidence":0.95}'
                ),
            ]
        )
    )
    reason_node = make_reason_node(fake_llm)
    result = reason_node({"raw_event": {...}, "triage_result": {"passed": True}})
    assert result["severity"] == "critical"


def test_full_graph_low_confidence_suppresses_alert():
    fake_llm = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(content='{"severity":"high","reasoning":"uncertain","confidence":0.2}'),
            ]
        )
    )
    graph = build_graph(llm=fake_llm, checkpointer=InMemorySaver())
    out = graph.invoke({"raw_event": {...}}, {"configurable": {"thread_id": "t1"}})
    assert out["should_alert"] is False
```

`GenericFakeChatModel` takes an iterator of responses (string or `AIMessage`), returning one per call — use `FakeListChatModel` when you just need canned text without message objects. If a node imports the LLM class at module level instead of receiving it via injection, patch it where it's *used* (the node's module), not where it's defined — a common source of "my mock isn't being hit" bugs. [LangChain unit testing docs](https://docs.langchain.com/oss/python/langchain/test/unit-testing)

For conditional-edge routing functions, test them directly as pure functions against hand-built state dicts — no LLM or graph compilation needed at all.

## 8. Common pitfalls / anti-patterns

- **Defaulting to `ChatBedrock` out of habit.** It's the older InvokeModel path; use `ChatBedrockConverse` unless you specifically need custom-model support. [Issue #349](https://github.com/langchain-ai/langchain-aws/issues/349)
- **Trusting `with_structured_output()`'s default forced `tool_choice` on every Claude model.** Some newer releases reject it with a 400 — fall back to `tool_choice="auto"` + explicit instruction if you hit this. [Issue #1310](https://github.com/langchain-ai/langchain-aws/issues/1310)
- **Assuming `max_retries` is honored end-to-end.** Verify actual retry behavior under simulated throttling rather than trusting the constructor arg silently works. [Issue #819](https://github.com/langchain-ai/langchain-aws/issues/819)
- **`InMemorySaver` in anything but dev/test.** It gives fundamentally different failure behavior (silent data loss on restart) than the Sqlite/Postgres savers you'll run in prod — test against the real checkpointer type.
- **Unbounded retry-routing loops.** A conditional edge that loops back to `reason` on every parse failure with no cap will run to `recursion_limit` (or beyond, if left at a high default) burning Bedrock spend on a broken schema.
- **Changing `EventState`'s shape without a migration plan.** Breaks deserialization of existing checkpoints on resume.
- **Treating verbalized `confidence` as calibrated probability.** It's a generated token like any other output — useful as a relative signal, not as ground truth. See §5.
- **Building a bespoke "LLM interface" abstraction when the Runnable protocol already gives you one.** Any `BaseChatModel` (fake or real) satisfies `.invoke`/`with_structured_output`; wrapping it in a custom interface layer is usually unneeded complexity for this project's scope.
