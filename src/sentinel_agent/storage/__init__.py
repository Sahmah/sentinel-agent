"""Event storage. SQLite by default; DynamoDB with SENTINEL_STORAGE_BACKEND=dynamodb.

Environment:
    SENTINEL_STORAGE_BACKEND   sqlite (default) or dynamodb
    SENTINEL_DB_PATH           SQLite file, default ./sentinel.db
    SENTINEL_DYNAMODB_TABLE    DynamoDB table, default sentinel-events
"""

import os

from sentinel_agent.storage.base import Storage


def build_storage() -> Storage:
    backend = os.environ.get("SENTINEL_STORAGE_BACKEND", "sqlite").lower()
    if backend == "sqlite":
        from sentinel_agent.storage.sqlite_store import SqliteStorage

        return SqliteStorage(os.environ.get("SENTINEL_DB_PATH", "sentinel.db"))
    if backend == "dynamodb":
        from sentinel_agent.storage.dynamodb_store import DynamoDbStorage

        return DynamoDbStorage(os.environ.get("SENTINEL_DYNAMODB_TABLE", "sentinel-events"))
    raise ValueError(f"Unknown SENTINEL_STORAGE_BACKEND {backend!r}: use sqlite or dynamodb")


def describe_storage() -> str:
    """Where `build_storage()` writes, for CLI messages."""
    if os.environ.get("SENTINEL_STORAGE_BACKEND", "sqlite").lower() == "dynamodb":
        return "DynamoDB table " + os.environ.get("SENTINEL_DYNAMODB_TABLE", "sentinel-events")
    return os.environ.get("SENTINEL_DB_PATH", "sentinel.db")
