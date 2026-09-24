"""Chat-model construction, retry/backoff, and response parsing.

Backend is picked by `SENTINEL_LLM_BACKEND`:
- `demo` (default): `DemoChatModel`, a deterministic local stand-in — zero
  cost, no AWS credentials, reproducible output.
- `bedrock`: `ChatBedrockConverse` against Claude on Amazon Bedrock. Model id
  from `SENTINEL_BEDROCK_MODEL_ID` (some regions require an inference-profile
  id such as `us.anthropic...` instead of the base model id), region from
  `AWS_REGION`.
- `ollama`: a local model served by Ollama (needs the `ollama` extra). Model
  from `SENTINEL_OLLAMA_MODEL`, server from `SENTINEL_OLLAMA_URL`. Free and
  offline; small models reason noticeably worse, see `sentinel eval-llm`.

Structured output is parsed by hand from plain JSON text rather than through
`with_structured_output()`: that path sends a forced `tool_choice`, which newer
Claude models on Bedrock reject with a 400 (langchain-aws issue #1310; see the
langgraph-bedrock skill, §2). Plain JSON plus validation works on every model.
"""

import json
import os
import random
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from sentinel_agent.agent.heuristic import heuristic_reasoning
from sentinel_agent.agent.prompts import EVENT_CLOSE, EVENT_OPEN
from sentinel_agent.agent.schemas import ReasoningOutput

DEFAULT_BEDROCK_MODEL_ID = "anthropic.claude-opus-5"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
RETRYABLE_AWS_ERRORS = ("ThrottlingException", "ServiceUnavailableException")


class ReasoningParseError(ValueError):
    """The model's reply did not contain a valid `ReasoningOutput` JSON object."""


class DemoChatModel(BaseChatModel):
    """Answers the reasoning prompt with `heuristic_reasoning`, serialized as
    the same JSON a real model is asked to produce. Reads the event from the
    `<event>` block of the last message, so it sees exactly what an LLM would."""

    @property
    def _llm_type(self) -> str:
        return "sentinel-demo"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = messages[-1].text
        start, end = text.find(EVENT_OPEN), text.find(EVENT_CLOSE)
        if start == -1 or end == -1:
            raise ValueError("DemoChatModel expects an <event>...</event> block in the prompt")
        payload = json.loads(text[start + len(EVENT_OPEN) : end])
        reply = heuristic_reasoning(payload).model_dump_json()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])


def build_llm(backend: str | None = None) -> BaseChatModel:
    backend = (backend or os.environ.get("SENTINEL_LLM_BACKEND", "demo")).lower()
    if backend == "demo":
        return DemoChatModel()
    if backend == "bedrock":
        # Imported lazily so demo mode never touches boto3 session/credential setup.
        from botocore.config import Config
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(
            model=os.environ.get("SENTINEL_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=1024,
            # botocore's own retries, as a first layer under invoke_with_backoff.
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
    if backend == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "The ollama backend needs the optional `ollama` extra: uv sync --extra ollama"
            ) from exc

        return ChatOllama(
            model=os.environ.get("SENTINEL_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            base_url=os.environ.get("SENTINEL_OLLAMA_URL", DEFAULT_OLLAMA_URL),
            # JSON mode constrains decoding to valid JSON: small models otherwise
            # wander into prose. temperature 0 keeps runs comparable in eval-llm.
            format="json",
            temperature=0,
            num_predict=400,
            # Loading a model takes ~45 s on a consumer GPU; keep it warm between events.
            keep_alive="30m",
        )
    raise ValueError(
        f"Unknown SENTINEL_LLM_BACKEND {backend!r}; expected 'demo', 'bedrock' or 'ollama'"
    )


def invoke_with_backoff(
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
    *,
    max_attempts: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> BaseMessage:
    """Second retry layer: botocore retries don't cover every throttling path
    (langgraph-bedrock skill, §6). Non-throttling errors propagate immediately."""
    for attempt in range(max_attempts):
        try:
            return llm.invoke(list(messages))
        except Exception as exc:
            response = getattr(exc, "response", None)  # botocore ClientError carries a dict
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code not in RETRYABLE_AWS_ERRORS or attempt == max_attempts - 1:
                raise
            sleep(min(60.0, 2**attempt + random.uniform(0, 1)))
    raise AssertionError("unreachable")


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_reasoning(text: str) -> ReasoningOutput:
    """Extract and validate the JSON object from a model reply. Tolerates code
    fences or stray prose around it, and a 0-100 confidence scale."""
    match = _JSON_OBJECT.search(text)
    if match is None:
        raise ReasoningParseError("no JSON object found in the reply")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ReasoningParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReasoningParseError("expected a JSON object")
    confidence = data.get("confidence")
    if isinstance(confidence, int | float) and 1 < confidence <= 100:
        data["confidence"] = confidence / 100
    try:
        return ReasoningOutput.model_validate(data)
    except ValidationError as exc:
        raise ReasoningParseError(str(exc)) from exc
