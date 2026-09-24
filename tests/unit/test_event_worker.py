import io
import threading

from sentinel_agent.cli import EventWorker


class _SlowGraph:
    """Stands in for the compiled graph: blocks until released, then fails on
    one event and succeeds on the others."""

    def __init__(self):
        self.release = threading.Event()
        self.seen: list[str] = []

    def invoke(self, state):
        self.release.wait(timeout=5)
        self.seen.append(state["event"]["id"])
        if state["event"]["id"] == "boom":
            raise RuntimeError("bedrock down")
        return {"action": "logged", "severity": "low", "reasoning": None}


def test_submit_does_not_block_and_order_is_kept(make_event):
    graph, out = _SlowGraph(), io.StringIO()
    worker = EventWorker(graph, out=out)
    # The graph is blocked, yet submit returns: the capture loop keeps running.
    worker.submit([make_event(id=i) for i in ("a", "boom", "b")])
    assert graph.seen == []
    graph.release.set()
    worker.close()
    assert graph.seen == ["a", "boom", "b"]
    lines = out.getvalue()
    assert "agent failed on person" in lines and "bedrock down" in lines
    assert lines.count("logged") == 2  # a failure doesn't stop later events
    assert worker.last_line == "person: logged"


def test_decisions_are_saved_and_a_save_failure_is_reported(make_event):
    graph, out, saved = _SlowGraph(), io.StringIO(), []
    graph.release.set()

    def save(decision):
        if decision.event.id == "b":
            raise OSError("disk full")
        saved.append(decision.event.id)

    worker = EventWorker(graph, save=save, out=out)
    worker.submit([make_event(id=i) for i in ("a", "b", "c")])
    worker.close()
    assert saved == ["a", "c"] and worker.saved == 2
    assert "could not save person" in out.getvalue() and "disk full" in out.getvalue()
