"""Default backend: one SQLite file, zero infrastructure.

The full record is stored as JSON; only the columns used for filtering and
ordering are broken out. A connection is opened per call, so the store can be
used from the webcam's agent thread and the capture thread alike.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from sentinel_agent.storage.base import (
    EventFilter,
    EventPage,
    EventRecord,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    iso_utc,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    action TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_time ON events (occurred_at DESC, id DESC);
"""


class SqliteStorage:
    def __init__(self, path: str | Path = "sentinel.db"):
        self.path = str(path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def save(self, record: EventRecord) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO events (id, camera_id, action, occurred_at, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.camera_id,
                    record.action,
                    iso_utc(record.occurred_at),
                    record.model_dump_json(),
                ),
            )

    def get(self, event_id: str) -> EventRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT data FROM events WHERE id = ?", (event_id,)).fetchone()
        return EventRecord.model_validate_json(row[0]) if row else None

    def query(self, filters: EventFilter, *, limit: int, cursor: str | None = None) -> EventPage:
        where, params = [], []
        if filters.camera_id is not None:
            where.append("camera_id = ?")
            params.append(filters.camera_id)
        if filters.action is not None:
            where.append("action = ?")
            params.append(filters.action)
        if filters.review == "unreviewed":
            where.append("json_extract(data, '$.review') IS NULL")
        elif filters.review is not None:
            where.append("json_extract(data, '$.review') = ?")
            params.append(filters.review)
        if filters.since is not None:
            where.append("occurred_at >= ?")
            params.append(iso_utc(filters.since))
        if filters.until is not None:
            where.append("occurred_at <= ?")
            params.append(iso_utc(filters.until))
        if cursor is not None:
            # Keyset pagination: resume strictly after the last row of the previous page.
            position = decode_cursor(cursor)
            if not (isinstance(position, list) and len(position) == 2):
                raise InvalidCursorError(f"Invalid cursor {cursor!r}")
            where.append("(occurred_at < ? OR (occurred_at = ? AND id < ?))")
            params += [position[0], position[0], position[1]]

        sql = "SELECT id, occurred_at, data FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, [*params, limit + 1]).fetchall()

        page = rows[:limit]
        next_cursor = encode_cursor([page[-1][1], page[-1][0]]) if len(rows) > limit else None
        return EventPage(
            events=[EventRecord.model_validate_json(r[2]) for r in page], next_cursor=next_cursor
        )
