from sentinel_agent.report import collect, render, write_report
from sentinel_agent.storage.base import EventFilter
from sentinel_agent.storage.sqlite_store import SqliteStorage


def test_report_counts_flags_and_links_crops(tmp_path, make_record):
    images = tmp_path / "snapshots"
    images.mkdir()
    (images / "evt-000.jpg").write_bytes(b"jpg")
    records = [
        make_record(0, id="evt-000", action="alert", snapshot="evt-000.jpg"),
        make_record(1, id="evt-001", action="human_review", disagreement=True, snapshot="gone.jpg"),
        make_record(2, id="evt-002", action="logged", review="real"),
    ]
    text = render(
        records, title="Test run", image_root=images, out_dir=tmp_path / "lab" / "reports"
    )
    assert "| alert | 1 |" in text and "| human_review | 1 |" in text
    assert "## Needs a person" in text
    needs = text.split("## Needs a person")[1].split("## All events")[0]
    assert "evt-000"[:8] in needs and "evt-001"[:8] in needs and "evt-002" not in needs
    assert "![person crop](../../snapshots/evt-000.jpg)" in text  # relative to the report
    assert "gone.jpg" not in text  # a missing crop is not linked
    assert "**disagreement**" in text and "reviewed: real" in text


def test_empty_period_says_so(tmp_path):
    assert "No events" in render([], title="t", image_root=tmp_path, out_dir=tmp_path)


def test_write_report_filters_by_run(tmp_path, make_record, monkeypatch):
    monkeypatch.setenv("SENTINEL_LAB_DIR", str(tmp_path / "lab"))
    store = SqliteStorage(tmp_path / "events.db")
    store.save(make_record(0, id="a", run_id="r1"))
    store.save(make_record(1, id="b", run_id="r2"))
    assert [r.id for r in collect(store, EventFilter(), run_id="r1")] == ["a"]
    path = write_report(store, title="Run r1", run_id="r1", name="r1")
    assert path == tmp_path / "lab" / "reports" / "r1.md"
    assert "1 events" in path.read_text()
