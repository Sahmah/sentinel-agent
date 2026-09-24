---
name: python-testing
description: Testing patterns (pytest, pytest-asyncio, moto, hypothesis) for a mixed CV/LangGraph/MCP/AWS codebase, used in the Sentinel Agent project
---

# Python testing for Sentinel Agent (CV + LangGraph + MCP + AWS)

Reference for a repo mixing OpenCV detection (sync), a LangGraph pipeline calling
Bedrock (async nodes), an MCP stdio server (async handlers), and boto3/S3/DynamoDB.
Assumes pytest, pytest-asyncio, hypothesis, moto, ruff.

## 1. Suite layout for mixed sync/async

Use **pytest-asyncio in `auto` mode** so async `def test_*` functions run without a
per-test `@pytest.mark.asyncio` marker — important here because LangGraph nodes and
MCP handlers are async but CV/calibration tests are plain sync functions, and you
don't want to remember the marker on every async test.

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

Strict mode is the default (only tests/fixtures explicitly marked `asyncio` run);
auto mode auto-marks every `async def test_*` and takes ownership of async fixtures
regardless of decorator. `asyncio_default_fixture_loop_scope` currently falls back to
the fixture's own scope when unset, and this default is slated to become `function`
in a future release — set it explicitly now to avoid the migration break.
(https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html)

Async fixture example:

```python
import pytest_asyncio


@pytest_asyncio.fixture
async def bedrock_agent_state():
    state = {"messages": [], "detections": []}
    yield state
```

Suggested directory split (keeps slow/async tests separable in CI):

```
tests/
  unit/
    test_detection.py, test_calibration.py, test_event_aggregation.py  # sync
    test_graph_nodes.py, test_mcp_handlers.py                          # async
  integration/
    test_graph_e2e.py, test_mcp_stdio.py, test_aws_moto.py             # async/moto
```

## 2. Mocking AWS: moto `@mock_aws`

As of moto 5.x (latest stable 5.2.3, Aug 2026) the **unified `@mock_aws` decorator**
is the current API — the old per-service decorators (`@mock_s3`, `@mock_dynamodb`,
etc.) are the legacy pre-5.0 pattern; don't reintroduce them.
(https://docs.getmoto.org/en/latest/docs/getting_started.html,
https://pypi.org/project/moto/)

```python
import os
import boto3
import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(scope="function")
def mocked_aws(aws_credentials):
    # start the mock BEFORE any boto3 client is constructed
    with mock_aws():
        yield


def test_event_persisted_to_dynamo_and_s3(mocked_aws):
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    s3.create_bucket(Bucket="sentinel-clips")
    table = ddb.create_table(
        TableName="sentinel-events",
        KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    # ... call code under test, which does boto3.client("s3")/("dynamodb") itself ...
    assert table.get_item(Key={"event_id": "evt-1"})["Item"]["status"] == "open"
```

Key rules:
- Construct boto3 clients/resources **inside** the mock context — module-level
  clients built at import time won't be mocked.
- `@mock_aws` also works as a bare decorator or plain context manager; prefer the
  fixture form above so credentials + mock setup are reusable across tests.
- moto also has a **server mode** (`moto_server`, real HTTP endpoint) for non-Python
  clients or Docker Compose setups — not needed here since everything is boto3
  in-process. (https://docs.getmoto.org/)

## 3. Testing LangGraph without hitting Bedrock

Inject a fake `BaseChatModel` instead of the real Bedrock client. `langchain_core`
ships `GenericFakeChatModel` / `FakeListChatModel` for this — same `Runnable`
interface your nodes call (`.invoke`/`.ainvoke`/streaming), works in async tests,
scriptable responses.

```python
from langchain_core.language_models.fake_chat_models import FakeListChatModel


def build_graph(chat_model):  # your factory takes a model, real code uses ChatBedrock
    ...


async def test_triage_node_escalates_on_high_confidence_detection():
    fake_model = FakeListChatModel(responses=["ESCALATE: person detected near restricted zone"])
    graph = build_graph(fake_model)

    result = await graph.ainvoke(
        {
            "detections": [{"label": "person", "confidence": 0.92, "zone": "restricted"}],
            "messages": [],
        }
    )

    assert result["decision"] == "ESCALATE"
    assert result["messages"][-1].content.startswith("ESCALATE")
```

Layer the tests: (1) **node-level** — call a single node function with a hand-built
state dict and fake model, assert the returned partial state, no compile needed;
(2) **graph/trajectory** — compile the real graph, `ainvoke`/`astream` with
`FakeListChatModel`/`GenericFakeChatModel` (multi-turn), assert final state *and*
which nodes ran; (3) **integration** (few, gated) — real `ChatBedrock` behind
`@pytest.mark.integration`, not run in default CI.

(https://python.langchain.com/v0.2/api_reference/core/language_models/langchain_core.language_models.fake_chat_models.GenericFakeChatModel.html,
https://getautonoma.com/blog/langgraph-testing)

Prefer dependency-injecting a fake model over `unittest.mock.patch`-ing
`boto3`/`ChatBedrock` internals — it's more robust to LangChain/LangGraph refactors.

## 4. Testing the MCP server

Two levels: unit-test the handler as a plain function first, then a thin
protocol-level check.

**a) Direct unit test** (bypass MCP transport — fastest, catches most bugs):

```python
from sentinel_agent.mcp_tools import get_event_snapshot  # the plain async function


async def test_get_event_snapshot_returns_expected_shape(mocked_aws):
    result = await get_event_snapshot(event_id="evt-1")
    assert result["event_id"] == "evt-1"
    assert "s3_uri" in result
```

If tools are registered via `@mcp.tool()` on a `FastMCP`/low-level `Server` instance,
keep the logic in an undecorated function and have the decorated wrapper call it —
that's what makes (a) possible without spinning up the server.

**b) In-memory protocol-level test** — verifies registration, JSON schema, and
serialization with no subprocess/socket. MCP Python SDK v2's `Client` talks directly
to a server object in-process:

```python
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from sentinel_agent.server import mcp  # the FastMCP/Server instance


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


async def test_mcp_tool_call_over_protocol(client: Client):
    result = await client.call_tool("get_event_snapshot", {"event_id": "evt-1"})
    assert result == CallToolResult(
        content=[TextContent(type="text", text='{"event_id": "evt-1", ...}')],
        structured_content={"event_id": "evt-1", "...": "..."},
    )
```

Use `raise_exceptions=True` in tests to get real tracebacks instead of the
production-safe "Internal server error" string.
(https://py.sdk.modelcontextprotocol.io/get-started/testing/)

If pinned to SDK v1 (`mcp<2`), the equivalent helper is
`mcp.shared.memory.create_connected_server_and_client_session` — it was removed in
the 2.0.0 stable release (2026-07-28) in favor of the unified `Client` above; check
your installed `mcp` version before copying older examples.
(https://py.sdk.modelcontextprotocol.io/whats-new/,
https://github.com/modelcontextprotocol/python-sdk)

A true end-to-end test over real stdio (spawns a subprocess) mainly re-covers
transport/serialization already exercised by (b) — keep it to one slow-marked test.

## 5. Where hypothesis actually earns its keep

**Worth it:**
- **Event-aggregation / temporal clustering** (raw per-frame detections → events):
  invariants like "no detection is lost", "output events are sorted and
  non-overlapping", "clustering is idempotent on its own output" are exactly what
  example-based tests under-cover.
  ```python
  from hypothesis import given, strategies as st

  hits = st.lists(st.tuples(st.floats(0, 3600), st.floats(0, 1)), max_size=200)


  @given(hits)
  def test_clustering_preserves_all_detections(frame_hits):
      events = cluster_into_events(frame_hits, gap_seconds=2.0)
      assert sum(len(e.detections) for e in events) == len(frame_hits)
  ```
- **Calibration math** (pixel↔world transforms, homography): round-trip properties
  (`world_to_pixel(pixel_to_world(p)) ≈ p`) are a natural fit and catch numerical
  edge cases (near-zero denominators, extreme aspect ratios) you wouldn't hand-write.
- Any pure function with a clear mathematical invariant and no I/O.

**Overkill / skip:**
- LangGraph node logic and MCP handlers — dominated by I/O and control flow, not
  numeric invariants; table-driven example tests communicate intent better.
- OpenCV frame-processing where "correct" is visually/semantically defined ("is this
  actually a person") — no oracle to assert against; use golden fixture images.
- Anything already trivially covered by 2-3 example cases with no real input space.

Hypothesis supplements, not replaces, example-based tests: it excels at edge cases
you didn't think of, but doesn't remove the need for tests documenting specific
expected behavior. (https://hypothesis.readthedocs.io/)

## 6. CI (GitHub Actions)

Single Python version is enough for a portfolio project (matrix adds CI time for
little signal unless you're supporting multiple runtimes); use `uv` with caching for
speed.

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v10
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"
      - run: uv sync --locked --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest --tb=short -q
```

`enable-cache: true` caches the uv package store keyed on the lockfile, so unchanged
deps skip re-download; `uv sync --locked` fails fast if `uv.lock` drifts from
`pyproject.toml`. (https://docs.astral.sh/uv/guides/integration/github/,
https://github.com/astral-sh/setup-uv)

If OpenCV tests need system libs (`libgl1`, `libglib2.0-0`) for headless
`cv2.imread`, add an `apt-get install` step before `uv sync` — a common gap in
uv-only CI for this kind of project.
