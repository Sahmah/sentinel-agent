---
name: mcp-best-practices
description: Best practices for building and testing MCP servers and clients in Python (2026 spec), used in the Sentinel Agent project
---

# MCP Python SDK — Best Practices (2026-07-28 spec)

Reference for building the Sentinel Agent's MCP server (`get_events`, `get_event`,
`list_alerts`) and any MCP client code the agent pipeline uses to consume tools.

## Spec baseline: what changed in 2026-07-28

Largest revision since MCP launched — build against it, don't copy 2024/2025 tutorials.
[blog.modelcontextprotocol.io/posts/2026-07-28](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

- **Stateless core.** `initialize`/`initialized` and `Mcp-Session-Id` are retired; every
  request carries protocol version, client identity, and capabilities in `_meta`. Don't
  rely on connection-scoped state — if `get_events` needs pagination, return an explicit
  cursor and have the model pass it back as an argument, don't assume server memory.
- **Header-based routing** via `Mcp-Method`/`Mcp-Name` HTTP headers (useful behind a proxy).
- **Multi round-trip requests (MRTR)** replace server-initiated requests for mid-call
  confirmation (`resultType: "input_required"`) — relevant if an alert tool ever needs
  human-in-the-loop confirmation.
- **Deprecated:** Roots, Sampling, Logging (12-month support window); legacy HTTP+SSE
  transport in favor of Streamable HTTP. Don't build new SSE-only servers.
- **Hardened authorization** — see below.

## Defining the server with FastMCP

FastMCP (`mcp.server.fastmcp.FastMCP` in the official SDK, or standalone `fastmcp`
package) derives JSON Schema from type hints/Pydantic models and validates input/output.

```python
from fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP("Sentinel Agent")


class EventQuery(BaseModel):
    camera_id: str = Field(description="Camera/source identifier")
    since: str = Field(description="ISO 8601 timestamp lower bound")
    limit: int = Field(default=50, ge=1, le=500)


class Event(BaseModel):
    id: str
    camera_id: str
    timestamp: str
    label: str
    confidence: float


@mcp.tool
def get_events(query: EventQuery) -> list[Event]:
    """Return detection events for a camera since a given timestamp."""
    ...
```

**Structured I/O**: always use Pydantic models for non-trivial args/returns, not loose
`dict`s — they generate the `inputSchema`/`outputSchema` and validate results before they
go over the wire. Object-like results (dict/model/dataclass) auto-become
`structuredContent`; primitives get wrapped as `{"result": ...}`. Output schemas **must**
be `type: object` at the root — wrap bare lists (`{"events": [...]}`) if you declare an
explicit `output_schema`.

### Tool vs Resource vs Prompt

- **Tool** (`@mcp.tool`) — an action/query the model actively invokes with arguments.
  `get_events`, `get_event`, `list_alerts` are tools: computed/filtered lookups.
- **Resource** (`@mcp.resource("scheme://{param}")`) — addressable, read-only data fetched
  by URI, no query logic (e.g. `sentinel://camera/{camera_id}/status`). Use for "fetch
  this known thing by id," not "search/filter."
- **Prompt** (`@mcp.prompt`) — a reusable server-side template (e.g. "summarize alerts for
  camera X"). Not needed for a first pass of Sentinel Agent.

```python
@mcp.resource("sentinel://camera/{camera_id}/status")
def camera_status(camera_id: str) -> dict:
    """Current online/offline status for a camera."""
    ...
```

Annotate read-only/mutating tools cheaply via `@mcp.tool(annotations=ToolAnnotations(
readOnlyHint=True, idempotentHint=True, openWorldHint=False))` (`from mcp.types import
ToolAnnotations`) — clients use these hints without spending context tokens.

## Error handling and validation

- Raise `fastmcp.exceptions.ToolError("message")` for expected, user-facing failures (bad
  camera id, bad timestamp) — `ToolError` text is always sent to the client verbatim.
- Set `FastMCP(..., mask_error_details=True)` in production so unexpected exceptions (bugs,
  DB errors) collapse to a generic message; only `ToolError` bypasses the mask.
- Use Pydantic constraints (`Field(ge=..., le=...)`, `Literal[...]`) instead of hand-rolled
  `if` checks.
- Never swallow exceptions and return `{"error": ...}` as a success payload — raise, so the
  result is marked `isError=True` and the model treats it as a failure, not data.

```python
from fastmcp.exceptions import ToolError


@mcp.tool
def get_event(event_id: str) -> Event:
    """Fetch a single detection event by id."""
    event = db.find(event_id)
    if event is None:
        raise ToolError(f"No event found with id={event_id!r}")
    return event
```

## Transports: stdio vs Streamable HTTP

- **stdio** — default for local dev and anything Claude Desktop/Code launches as a
  subprocess. No network exposure, no auth needed (spec: STDIO implementations **should
  not** do the OAuth flow — pull secrets from the environment). Use for local demo.
  `mcp.run()` defaults to stdio.
- **Streamable HTTP** — for a standalone deployed service (vision pipeline's MCP server in
  a container, called remotely). The only non-deprecated network transport now.
  ```python
  mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
  ```
  Or: `mcp run server.py --transport streamable-http`. Don't build new SSE-only servers.

## Building an MCP client in Python

Useful for testing Sentinel's own server, and if the agent pipeline should call
*external* MCP tools.

```python
import asyncio
from fastmcp import Client


async def main():
    async with Client("sentinel_mcp_server.py") as client:  # stdio, inferred from path
        tools = await client.list_tools()
        result = await client.call_tool(
            "get_events",
            {"query": {"camera_id": "cam-01", "since": "2026-09-23T00:00:00Z"}},
        )
        print(result.data)

    async with Client("https://sentinel.example.com/mcp") as client:  # Streamable HTTP
        result = await client.call_tool("list_alerts", {})
        print(result.data)


asyncio.run(main())
```

Always use `async with Client(...)` for lifecycle management. `Client(...)` accepts a path
(stdio), a URL (Streamable HTTP), or an explicit transport
(`PythonStdioTransport(..., env={...})`) to pass env vars to a spawned subprocess. Pin
protocol version during a migration window with `Client(url, mode="2026-07-28")`.

## Authorization (hardened in 2026-07-28)

Optional in MCP, but when used it's now a real OAuth 2.1 deployment.
[modelcontextprotocol.io/specification/2026-07-28/basic/authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

- **STDIO servers should NOT implement this spec** — use env vars/`.env` for credentials.
  Covers Sentinel Agent's local demo mode.
- **HTTP servers are OAuth 2.1 resource servers**, not identity providers: validate bearer
  tokens, don't issue them. **Token passthrough is an explicit spec anti-pattern** — never
  forward a received token downstream without validating it was audience-bound to your
  server (RFC 8707).
- Servers **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC 9728) at
  `/.well-known/oauth-protected-resource`, returning `401` + `WWW-Authenticate: Bearer
  resource_metadata="..."` (with a `scope` hint) when unauthenticated.
- **Dynamic Client Registration (RFC 7591) is deprecated** in favor of Client ID Metadata
  Documents (CIMD) — an HTTPS URL used directly as `client_id`. Prefer CIMD or a
  pre-registered client in new client code.
- Clients **MUST** validate `iss` on the authorization response per RFC 9207 (mix-up-attack
  mitigation) and **MUST** send `resource` (RFC 8707) on both authorization and token
  requests, set to the server's canonical URI.
- If Sentinel's MCP server is ever deployed publicly, put a real OAuth 2.1 resource-server
  layer in front rather than hand-rolling token validation.

## Testing strategy

Unit-test tool logic directly — a `@mcp.tool`-decorated function is still a plain Python
function you can import and call:

```python
from sentinel_mcp_server import get_event
from fastmcp.exceptions import ToolError
import pytest


def test_get_event_not_found():
    with pytest.raises(ToolError):
        get_event(event_id="does-not-exist")
```

Integration-test through a real in-memory client to exercise schema validation and the
actual MCP call path — no subprocess/network needed, bind `Client` directly to the server:

```python
import pytest
from fastmcp import Client
from sentinel_mcp_server import mcp


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.asyncio
async def test_list_alerts_returns_structured_data(client):
    result = await client.call_tool("list_alerts", {})
    assert isinstance(result.data, list)
```

`raise_exceptions=True` surfaces infrastructure bugs as real exceptions; tool-level
`ToolError`s still come back as `isError=True` results either way.

## Claude Desktop / Claude Code setup

**Claude Code**:

```bash
claude mcp add --transport stdio sentinel -- python sentinel_mcp_server.py
claude mcp add --transport http sentinel https://sentinel.example.com/mcp
```

Or in `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "sentinel": { "command": "python", "args": ["sentinel_mcp_server.py"] }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "sentinel": {
      "command": "python",
      "args": ["/absolute/path/to/sentinel_mcp_server.py"],
      "env": { "SENTINEL_DB_URL": "postgresql://..." }
    }
  }
}
```

Paths in `args` must be absolute; restart the app after editing. Debug logs:
`~/Library/Logs/Claude/mcp*.log` (macOS), specifically `mcp-server-SERVERNAME.log` for
stderr from your server.
[modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers)

## Common pitfalls / anti-patterns

- **God tools.** Don't wrap every endpoint 1:1. Three focused tools beat ten thin CRUD
  wrappers — fewer descriptions in context, less chance the model picks the wrong one.
- **Unbounded/raw output.** Don't return raw DB rows or image blobs from `get_events`. Cap
  `limit`, paginate, return only fields needed for reasoning — large outputs blow the
  context window and degrade quality.
- **Unsanitized content.** Treat any user/model-influenced free text in events/alerts as
  data, never as trusted instructions.
- **Synchronous long-running calls.** MCP tool calls have no async callback — design
  slow work (e.g. re-running inference) as submit → job id → separate `get_job_status`
  poll tool.
- **Token passthrough** on authenticated servers — spec-called-out anti-pattern.
- **Relying on session state** the stateless core no longer guarantees — pass
  cursors/handles explicitly as arguments.
- **Skipping structured output.** Loose dicts/strings instead of Pydantic models make the
  schema vague and skip FastMCP's automatic validation.

## Sources

- [MCP 2026-07-28 spec announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Authorization spec (2026-07-28)](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Connect to local MCP servers](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers)
- [python-sdk GitHub repo](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK docs](https://py.sdk.modelcontextprotocol.io/v1/)
- [FastMCP docs — tools](https://gofastmcp.com/servers/tools)
- [FastMCP docs — clients](https://gofastmcp.com/clients/client)
- [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)
