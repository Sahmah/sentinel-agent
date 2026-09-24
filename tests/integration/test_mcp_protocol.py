"""Through a real in-memory MCP client: schemas, serialization, error mapping.

The client is opened inside each test, not in a yield fixture: anyio cancel scopes
must be exited by the task that entered them, and pytest-asyncio runs fixture
teardown in a different task."""

import pytest
from mcp import Client

from sentinel_agent.mcp_server.server import build_server
from sentinel_agent.storage.sqlite_store import SqliteStorage


@pytest.fixture
def server(tmp_path, make_record):
    store = SqliteStorage(tmp_path / "events.db")
    for minute in range(3):
        store.save(make_record(minute, action="alert" if minute == 2 else "logged"))
    return build_server(store)


async def test_tools_are_listed_read_only_with_schemas(server):
    async with Client(server, raise_exceptions=True) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"list_events", "get_event", "summarize_events"}
        for tool in tools.values():
            assert tool.annotations.read_only_hint is True
            assert tool.output_schema is not None
        limit = tools["list_events"].input_schema["properties"]["limit"]
        assert (limit["minimum"], limit["maximum"]) == (1, 100)


async def test_list_then_get(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("list_events", {"action": "alert"})
        assert not result.is_error
        (event,) = result.structured_content["events"]
        assert event["occurred_at"] == "2026-09-24T12:02:00.000000Z"

        result = await client.call_tool("get_event", {"event_id": event["id"]})
        assert result.structured_content["reasoning"] == "Person entered the restricted zone."


async def test_pagination_round_trips_the_cursor(server):
    async with Client(server, raise_exceptions=True) as client:
        first = (await client.call_tool("list_events", {"limit": 2})).structured_content
        rest = await client.call_tool("list_events", {"limit": 2, "cursor": first["next_cursor"]})
        ids = [e["id"] for e in first["events"] + rest.structured_content["events"]]
        assert ids == ["evt-002", "evt-001", "evt-000"]


async def test_errors_come_back_as_tool_errors(server):
    async with Client(server, raise_exceptions=True) as client:
        missing = await client.call_tool("get_event", {"event_id": "nope"})
        assert missing.is_error and "No event with id 'nope'" in missing.content[0].text

        too_big = await client.call_tool("list_events", {"limit": 500})
        assert too_big.is_error and "less than or equal to 100" in too_big.content[0].text


async def test_summary(server):
    async with Client(server, raise_exceptions=True) as client:
        s = (await client.call_tool("summarize_events", {})).structured_content
        assert s["total"] == 3 and s["by_action"] == {"logged": 2, "alert": 1}
