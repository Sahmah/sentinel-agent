import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from sentinel_agent.agent.graph import build_graph
from sentinel_agent.agent.llm import build_llm
from sentinel_agent.cli import _parse_seeds
from sentinel_agent.evaluation import evaluate_llm


def test_demo_heuristic_separates_real_from_false():
    report = evaluate_llm(build_graph(build_llm("demo")), seeds=[1, 2])
    m = report.metrics()
    assert m["events"] > m["real"] >= 2
    assert m["parse_failures"] == 0
    assert m["auroc"] == 1.0
    assert m["mean_p_llm_real"] > m["mean_p_llm_false"]
    assert m["false_alerted"] == 0


def test_unparseable_replies_are_counted_not_scored():
    garbage = GenericFakeChatModel(messages=iter([AIMessage(content="no json here")] * 100))
    graph = build_graph(garbage, sleep=lambda _: None)
    m = evaluate_llm(graph, seeds=[1]).metrics()
    assert m["parse_failures"] == m["events"] > 0
    assert m["auroc"] is None and m["ece"] is None
    assert m["human_review"] == m["events"]  # an unparsed reply goes to a human


@pytest.mark.parametrize(("text", "seeds"), [("3", [3]), ("1-3", [1, 2, 3]), ("1-2,7", [1, 2, 7])])
def test_parse_seeds(text, seeds):
    assert _parse_seeds(text) == seeds


def test_ollama_backend_is_configured_for_json(monkeypatch):
    pytest.importorskip("langchain_ollama")
    monkeypatch.setenv("SENTINEL_OLLAMA_MODEL", "some-model:1b")
    monkeypatch.setenv("SENTINEL_OLLAMA_URL", "http://example:11434")
    llm = build_llm("ollama")  # constructing it makes no network call
    assert (llm.model, llm.base_url, llm.format, llm.temperature) == (
        "some-model:1b",
        "http://example:11434",
        "json",
        0,
    )
