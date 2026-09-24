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
