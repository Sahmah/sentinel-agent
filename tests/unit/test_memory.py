from datetime import UTC, datetime, timedelta

from sentinel_agent.agent.prompts import build_messages
from sentinel_agent.memory import Example, ReviewMemory
from sentinel_agent.storage.sqlite_store import SqliteStorage


def _ex(id, verdict, dets=2, zone=True, label="dog", camera="webcam", minutes=0):
    return Example(
        id=id,
        camera_id=camera,
        label=label,
        entered_restricted_zone=zone,
        detection_count=dets,
        duration_seconds=dets / 5,
        verdict=verdict,
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC) + timedelta(minutes=minutes),
    )


def test_picks_similar_examples_of_the_same_camera_and_label(make_event):
    memory = ReviewMemory(
        lambda: [
            _ex("close", "false_alarm", dets=2),
            _ex("long", "real", dets=80),
            _ex("other-label", "false_alarm", label="person"),
            _ex("other-camera", "false_alarm", camera="door"),
            _ex("self", "real"),
        ],
        k=2,
    )
    event = make_event(id="self", camera_id="webcam", label="dog", detection_count=2)
    picked = [e.id for e in memory.examples_for(event)]
    assert picked == ["close", "long"]  # nearest first; never itself, other labels or cameras


def test_balances_verdicts_when_the_nearest_all_agree(make_event):
    examples = [_ex(f"f{i}", "false_alarm", dets=2, minutes=i) for i in range(5)]
    examples.append(_ex("r", "real", dets=60))
    memory = ReviewMemory(lambda: examples, k=3)
    picked = memory.examples_for(make_event(camera_id="webcam", label="dog", detection_count=2))
    assert {e.verdict for e in picked} == {"false_alarm", "real"}
    assert picked[0].id == "f4"  # among equally similar, the most recent first


def test_reloads_reviews_made_during_a_run(tmp_path, make_record, make_event):
    store = SqliteStorage(tmp_path / "events.db")
    store.save(make_record(0, id="a", camera_id="webcam", label="dog", review="false_alarm"))
    memory = ReviewMemory.from_storage(store, "webcam", refresh_seconds=0)
    assert len(memory) == 1
    store.save(make_record(1, id="b", camera_id="webcam", label="dog", review="real"))
    store.save(make_record(2, id="c", camera_id="webcam", label="dog"))  # not reviewed
    assert len(memory) == 2


def test_prompt_lists_examples_and_numbers_their_images(make_event):
    event = make_event(label="dog")
    messages = build_messages(
        event,
        image=b"event-jpg",
        examples=[(_ex("a", "false_alarm"), b"example-jpg"), (_ex("b", "real", dets=60), None)],
    )
    text = messages[-1].text
    assert "<reviewed_examples>" in text
    assert "1. reviewed as FALSE ALARM: detected as dog" in text and "(image 2)" in text
    assert "2. reviewed as REAL" in text
    images = [b for b in messages[-1].content if isinstance(b, dict) and b.get("type") == "image"]
    assert len(images) == 2
    assert "<event>" in text  # the demo model still finds the event block
