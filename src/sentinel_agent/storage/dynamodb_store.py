"""Optional backend: DynamoDB (SENTINEL_STORAGE_BACKEND=dynamodb).

Table layout (`create_table` below; infra/ must match):
- partition key `id`
- GSI `by_time`: partition key `kind` (always "event"), sort key `occurred_at`,
  so "newest events" is one ordered Query instead of a Scan.

A single constant GSI partition caps write throughput at roughly 1,000 events/s,
far above what a few cameras produce. Sharding `kind` would lift the cap at the
cost of merging shards on read.
"""

import json
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

from sentinel_agent.storage.base import (
    EventFilter,
    EventPage,
    EventRecord,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    iso_utc,
)

TIME_INDEX = "by_time"
KIND = "event"


def create_table(name: str, *, dynamodb: Any = None) -> None:
    """For tests and local experiments; real tables come from infra/."""
    dynamodb = dynamodb or boto3.resource("dynamodb")
    table = dynamodb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "kind", "AttributeType": "S"},
            {"AttributeName": "occurred_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": TIME_INDEX,
                "KeySchema": [
                    {"AttributeName": "kind", "KeyType": "HASH"},
                    {"AttributeName": "occurred_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()


def _to_item(record: EventRecord) -> dict:
    # DynamoDB rejects Python floats (it wants Decimal). None attributes are
    # dropped rather than stored as NULL.
    data = json.loads(record.model_dump_json(), parse_float=Decimal)
    return {k: v for k, v in data.items() if v is not None} | {"kind": KIND}


def _from_item(item: dict) -> EventRecord:
    data = {k: v for k, v in item.items() if k != "kind"}
    return EventRecord.model_validate_json(json.dumps(data, default=float))


class DynamoDbStorage:
    def __init__(self, table_name: str = "sentinel-events", *, dynamodb: Any = None):
        # Resource created here, not at import, so moto's mock_aws can intercept it.
        self.table = (dynamodb or boto3.resource("dynamodb")).Table(table_name)

    def save(self, record: EventRecord) -> None:
        self.table.put_item(Item=_to_item(record))

    def get(self, event_id: str) -> EventRecord | None:
        item = self.table.get_item(Key={"id": event_id}).get("Item")
        return _from_item(item) if item else None

    def query(self, filters: EventFilter, *, limit: int, cursor: str | None = None) -> EventPage:
        key = Key("kind").eq(KIND)
        since = iso_utc(filters.since) if filters.since else None
        until = iso_utc(filters.until) if filters.until else None
        if since and until:
            key &= Key("occurred_at").between(since, until)
        elif since:
            key &= Key("occurred_at").gte(since)
        elif until:
            key &= Key("occurred_at").lte(until)

        conditions = []
        if filters.camera_id is not None:
            conditions.append(Attr("camera_id").eq(filters.camera_id))
        if filters.action is not None:
            conditions.append(Attr("action").eq(filters.action))
        if filters.review == "unreviewed":
            conditions.append(Attr("review").not_exists())  # None fields are not stored
        elif filters.review is not None:
            conditions.append(Attr("review").eq(filters.review))

        start_key = None
        if cursor is not None:
            start_key = decode_cursor(cursor)
            if not isinstance(start_key, dict):
                raise InvalidCursorError(f"Invalid cursor {cursor!r}")

        items: list[dict] = []
        while len(items) < limit:
            # Limit applies before the filter, so asking for exactly what is still
            # missing means LastEvaluatedKey never lands past an item we dropped.
            kwargs: dict = {
                "IndexName": TIME_INDEX,
                "KeyConditionExpression": key,
                "ScanIndexForward": False,
                "Limit": limit - len(items),
            }
            if conditions:
                expression = conditions[0]
                for c in conditions[1:]:
                    expression &= c
                kwargs["FilterExpression"] = expression
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = self.table.query(**kwargs)
            items += response["Items"]
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

        next_cursor = encode_cursor(start_key) if start_key else None
        return EventPage(events=[_from_item(i) for i in items], next_cursor=next_cursor)
