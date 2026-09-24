"""HTTP API over the event store, for the dashboard (`sentinel serve`).

    GET  /api/summary                 counts, same as the MCP summarize_events tool
    GET  /api/events                  newest first, filters + cursor, same as list_events
    GET  /api/events/{id}             one event
    POST /api/events/{id}/review      {"verdict": "real" | "false_alarm"}
    GET  /api/snapshots/{file}        a crop or scene JPEG
    GET  /api/stream                  Server-Sent Events: each newly stored event

The query logic is `mcp_server.tools`, so the dashboard and Claude (over MCP)
see exactly the same data. The stream polls the store rather than being pushed
to: the webcam and demo write from another process, and a one-second poll on
an indexed query is cheaper than any cross-process channel.

Binds to 127.0.0.1 by default and has no authentication: it serves camera
snapshots, so exposing it beyond the machine would need an auth layer first.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from sentinel_agent.mcp_server import tools
from sentinel_agent.snapshots import snapshot_dir
from sentinel_agent.storage import build_storage
from sentinel_agent.storage.base import EventFilter, Storage, apply_review

# Only names the snapshot writer produces: a UUID, optionally "_scene", ".jpg".
SNAPSHOT_NAME = re.compile(r"^[0-9a-f-]{36}(_scene)?\.jpg$")
REVIEW_VERDICTS = ("real", "false_alarm")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _datetime_param(request: Request, name: str) -> datetime | None:
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"`{name}` must be an ISO 8601 timestamp, got {value!r}") from exc


def build_app(
    storage: Storage | None = None,
    *,
    snapshots: Path | None = None,
    frontend: Path | None = None,
    poll_seconds: float = 1.0,
    stream_max_seconds: float | None = None,
) -> Starlette:
    """`stream_max_seconds` ends each /api/stream response after that long (tests);
    by default the stream runs until the client disconnects."""
    storage = storage if storage is not None else build_storage()
    snapshots = snapshots or snapshot_dir()

    async def summary(request: Request) -> Response:
        result = await asyncio.to_thread(
            tools.summarize_events,
            storage,
            camera_id=request.query_params.get("camera_id"),
            since=_datetime_param(request, "since"),
            until=_datetime_param(request, "until"),
        )
        return JSONResponse(result.model_dump(mode="json"))

    async def list_events(request: Request) -> Response:
        params = request.query_params
        try:
            limit = int(params.get("limit", 20))
        except ValueError:
            return _error(400, "`limit` must be an integer")
        page = await asyncio.to_thread(
            tools.list_events,
            storage,
            camera_id=params.get("camera_id"),
            action=params.get("action"),
            since=_datetime_param(request, "since"),
            until=_datetime_param(request, "until"),
            limit=max(1, limit),
            cursor=params.get("cursor"),
        )
        return JSONResponse(page.model_dump(mode="json"))

    async def get_event(request: Request) -> Response:
        record = await asyncio.to_thread(tools.get_event, storage, request.path_params["id"])
        return JSONResponse(record.model_dump(mode="json"))

    async def review(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(400, "body must be JSON")
        verdict = body.get("verdict") if isinstance(body, dict) else None
        if verdict not in REVIEW_VERDICTS:
            return _error(400, f"`verdict` must be one of {list(REVIEW_VERDICTS)}")
        record = await asyncio.to_thread(apply_review, storage, request.path_params["id"], verdict)
        if record is None:
            return _error(404, f"No event with id {request.path_params['id']!r}")
        return JSONResponse(record.model_dump(mode="json"))

    async def snapshot(request: Request) -> Response:
        name = request.path_params["name"]
        path = snapshots / name
        if not SNAPSHOT_NAME.match(name) or not path.is_file():
            return _error(404, "No such snapshot")
        # Snapshots never change once written.
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400, immutable"})

    async def stream(request: Request) -> Response:
        async def events() -> AsyncIterator[str]:
            # Start from what is already stored: the client loads that with /api/events,
            # and the stream only announces what arrives after it connected.
            seen = await asyncio.to_thread(_newest_ids, storage)
            idle = elapsed = 0.0
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                if stream_max_seconds is not None and elapsed >= stream_max_seconds:
                    return
                page = await asyncio.to_thread(storage.query, EventFilter(), limit=20)
                fresh = [r for r in reversed(page.events) if r.id not in seen]
                for record in fresh:
                    seen.add(record.id)
                    yield f"event: event\ndata: {record.model_dump_json()}\n\n"
                idle = 0.0 if fresh else idle + poll_seconds
                if idle >= 15:  # a comment line keeps proxies from closing an idle stream
                    idle = 0.0
                    yield ": keep-alive\n\n"
                await asyncio.sleep(poll_seconds)
                elapsed += poll_seconds

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    routes = [
        Route("/api/summary", summary),
        Route("/api/events", list_events),
        Route("/api/events/{id}", get_event),
        Route("/api/events/{id}/review", review, methods=["POST"]),
        Route("/api/snapshots/{name}", snapshot),
        Route("/api/stream", stream),
    ]
    if frontend is not None and frontend.is_dir():
        # The built dashboard (a static SPA); index.html answers unknown paths.
        routes.append(Mount("/", app=_SpaFiles(directory=frontend, html=True)))

    async def tool_error(request: Request, exc: Exception) -> Response:
        status = 404 if str(exc).startswith("No event") else 400
        return _error(status, str(exc))

    async def validation_error(request: Request, exc: Exception) -> Response:
        return _error(400, str(exc))

    return Starlette(
        routes=routes,
        exception_handlers={ToolError: tool_error, ValidationError: validation_error},
    )


def _newest_ids(storage: Storage) -> set[str]:
    return {r.id for r in storage.query(EventFilter(), limit=100).events}


class _SpaFiles(StaticFiles):
    """Static files, falling back to index.html so client-side routes survive a reload."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)
