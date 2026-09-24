import threading
import time

import pytest
from starlette.testclient import TestClient

from sentinel_agent.api import build_app
from sentinel_agent.storage.sqlite_store import SqliteStorage

EVENT_ID = "0f0e0d0c-0b0a-4908-8706-050403020100"


@pytest.fixture
def store(tmp_path, make_record):
    store = SqliteStorage(tmp_path / "events.db")
    for minute in range(3):
        store.save(make_record(minute, action="alert" if minute == 2 else "logged"))
    store.save(make_record(3, id=EVENT_ID, action="human_review", snapshot=f"{EVENT_ID}.jpg"))
    return store


@pytest.fixture
def snapshots(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / f"{EVENT_ID}.jpg").write_bytes(b"\xff\xd8fake-jpeg")
    (directory / "secret.txt").write_text("not a snapshot")
    return directory


@pytest.fixture
def client(store, snapshots):
    return TestClient(build_app(store, snapshots=snapshots))


def test_list_filter_and_paginate(client):
    page = client.get("/api/events", params={"limit": 2}).json()
    assert [e["id"] for e in page["events"]] == [EVENT_ID, "evt-002"]
    rest = client.get("/api/events", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [e["id"] for e in rest["events"]] == ["evt-001", "evt-000"]
    alerts = client.get("/api/events", params={"action": "alert"}).json()["events"]
    assert [e["id"] for e in alerts] == ["evt-002"]


def test_bad_input_is_a_400_not_a_500(client):
    assert client.get("/api/events", params={"action": "explode"}).status_code == 400
    assert client.get("/api/events", params={"since": "yesterday"}).status_code == 400
    assert client.get("/api/events", params={"cursor": "garbage"}).status_code == 400
    assert client.get("/api/events", params={"limit": "many"}).status_code == 400


def test_get_event_and_404(client):
    assert client.get(f"/api/events/{EVENT_ID}").json()["action"] == "human_review"
    assert client.get("/api/events/nope").status_code == 404


def test_review_is_stored_and_counted(client):
    response = client.post(f"/api/events/{EVENT_ID}/review", json={"verdict": "false_alarm"})
    assert response.status_code == 200
    assert response.json()["review"] == "false_alarm"
    assert response.json()["reviewed_at"].endswith("Z")
    summary = client.get("/api/summary").json()
    assert (summary["reviewed"], summary["reviewed_false_alarm"]) == (1, 1)

    assert (
        client.post(f"/api/events/{EVENT_ID}/review", json={"verdict": "maybe"}).status_code == 400
    )
    assert client.post("/api/events/nope/review", json={"verdict": "real"}).status_code == 404


def test_snapshots_only_serve_snapshot_files(client):
    ok = client.get(f"/api/snapshots/{EVENT_ID}.jpg")
    assert ok.status_code == 200 and ok.content.startswith(b"\xff\xd8")
    assert client.get("/api/snapshots/secret.txt").status_code == 404
    assert client.get("/api/snapshots/..%2Fevents.db").status_code == 404


def test_stream_announces_only_new_events(store, snapshots, make_record):
    app = build_app(store, snapshots=snapshots, poll_seconds=0.05, stream_max_seconds=1.5)

    def add_later():
        time.sleep(0.3)
        store.save(make_record(9, id="evt-new", action="alert"))

    threading.Thread(target=add_later).start()
    with TestClient(app) as client, client.stream("GET", "/api/stream") as response:
        body = "".join(response.iter_text())
    assert response.headers["content-type"].startswith("text/event-stream")
    data_lines = [line for line in body.splitlines() if line.startswith("data: ")]
    assert len(data_lines) == 1 and '"id":"evt-new"' in data_lines[0]


def test_serves_the_dashboard_with_spa_fallback(store, snapshots, tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<html>dashboard</html>")
    client = TestClient(build_app(store, snapshots=snapshots, frontend=build))
    assert "dashboard" in client.get("/").text
    assert "dashboard" in client.get("/events/some-id").text  # client-side route
    assert client.get("/api/events/nope").status_code == 404  # API is not swallowed
