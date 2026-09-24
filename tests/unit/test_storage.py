"""The same contract, run against both backends (DynamoDB through moto)."""

from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from sentinel_agent.storage.base import EventFilter, InvalidCursorError, encode_cursor
from sentinel_agent.storage.dynamodb_store import DynamoDbStorage, create_table
from sentinel_agent.storage.sqlite_store import SqliteStorage


@pytest.fixture
def aws_credentials(monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(params=["sqlite", "dynamodb"])
def store(request, tmp_path):
    if request.param == "sqlite":
        yield SqliteStorage(tmp_path / "events.db")
        return
    request.getfixturevalue("aws_credentials")
    with mock_aws():  # started before any boto3 resource exists
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        create_table("events", dynamodb=dynamodb)
        yield DynamoDbStorage("events", dynamodb=dynamodb)


def _ids(page):
    return [r.id for r in page.events]


def test_round_trip_keeps_every_field(store, make_record):
    record = make_record(
        llm_confidence=None,
        combined_confidence=None,
        severity=None,
        reasoning=None,
        is_true_positive=None,
        p_cv=0.123456789,
    )
    store.save(record)
    assert store.get(record.id) == record
    assert store.get("missing") is None


def test_save_replaces_by_id(store, make_record):
    store.save(make_record(action="logged"))
    store.save(make_record(action="alert"))
    page = store.query(EventFilter(), limit=10)
    assert [r.action for r in page.events] == ["alert"]


def test_query_is_newest_first_and_filters(store, make_record):
    store.save(make_record(0, camera_id="cam-01", action="alert"))
    store.save(make_record(1, camera_id="cam-02", action="logged"))
    store.save(make_record(2, camera_id="cam-01", action="logged"))
    store.save(make_record(3, camera_id="cam-01", action="alert"))

    assert _ids(store.query(EventFilter(), limit=10)) == [
        "evt-003",
        "evt-002",
        "evt-001",
        "evt-000",
    ]
    assert _ids(store.query(EventFilter(camera_id="cam-01", action="alert"), limit=10)) == [
        "evt-003",
        "evt-000",
    ]
    window = EventFilter(
        since=datetime(2026, 9, 24, 12, 1, tzinfo=UTC),
        until=datetime(2026, 9, 24, 12, 2, tzinfo=UTC),
    )
    assert _ids(store.query(window, limit=10)) == ["evt-002", "evt-001"]  # both ends inclusive


def test_filters_by_review(store, make_record):
    store.save(make_record(0, review="real"))
    store.save(make_record(1, review="false_alarm"))
    store.save(make_record(2))

    assert _ids(store.query(EventFilter(review="real"), limit=10)) == ["evt-000"]
    assert _ids(store.query(EventFilter(review="false_alarm"), limit=10)) == ["evt-001"]
    assert _ids(store.query(EventFilter(review="unreviewed"), limit=10)) == ["evt-002"]


def test_pagination_visits_every_match_once(store, make_record):
    for minute in range(12):
        store.save(make_record(minute, action="alert" if minute % 3 == 0 else "logged"))

    for filters, expected in [(EventFilter(), 12), (EventFilter(action="alert"), 4)]:
        seen, cursor = [], None
        while True:
            page = store.query(filters, limit=3, cursor=cursor)
            assert len(page.events) <= 3
            seen += _ids(page)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == expected
        assert seen == sorted(seen, reverse=True)


def test_rejects_a_cursor_it_did_not_issue(store):
    for bad in ["not base64 !!", encode_cursor("just a string")]:
        with pytest.raises(InvalidCursorError):
            store.query(EventFilter(), limit=5, cursor=bad)


def test_timestamps_sort_as_strings_with_zero_microseconds(make_record):
    # Pydantic would serialize 12:00:00 as "...12:00:00Z" and 12:00:00.5 as "...12:00:00.500000Z";
    # compared as strings those sort the wrong way round.
    record = make_record(0)
    assert record.model_dump()["occurred_at"].endswith("12:00:00.000000Z")
