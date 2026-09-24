import numpy as np
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from sentinel_agent.agent.graph import build_graph
from sentinel_agent.agent.llm import DemoChatModel
from sentinel_agent.calibration.calibrators import PlattCalibrator
from sentinel_agent.detection.classical import ClassicalCVDetector
from sentinel_agent.detection.scenario import generate_scenario, label_detections
from sentinel_agent.events.aggregator import cluster_into_events


def _config(thread: str = "cam-01") -> dict:
    return {"configurable": {"thread_id": thread}}


async def test_full_graph_with_fake_llm_alerts(make_event):
    llm = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content='{"severity": "high", "reasoning": "r", "confidence": 0.9, '
                    '"confidence_basis": "b"}'
                )
            ]
        )
    )
    graph = build_graph(llm, checkpointer=InMemorySaver())
    out = await graph.ainvoke({"event": make_event().model_dump(), "p_cv": 0.95}, _config())
    assert out["action"] == "alert"
    assert out["combined_confidence"] > 0.9


async def test_triaged_out_event_does_not_inherit_previous_results(make_event):
    """Same camera thread, so the checkpointer carries state between events."""
    graph = build_graph(DemoChatModel(), checkpointer=InMemorySaver())
    first = await graph.ainvoke({"event": make_event().model_dump(), "p_cv": 0.95}, _config())
    assert first["severity"] == "high"

    clutter = make_event(id="evt-2", label="object", entered_restricted_zone=False)
    second = await graph.ainvoke({"event": clutter.model_dump(), "p_cv": 0.95}, _config())
    assert second["action"] == "dismissed"
    assert second["severity"] is None
    assert second["llm_confidence"] is None


def test_synthetic_scenario_end_to_end():
    """The whole zero-AWS path: pixels -> detections -> events -> calibration -> agent.
    Calibration is fit on one seed and applied to another, so it's out-of-sample."""
    detector = ClassicalCVDetector()

    def run(seed: int):
        detections = []
        for f in generate_scenario(seed=seed):
            detections += label_detections(
                f,
                detector.detect(
                    f.frame, camera_id=f.camera_id, frame_index=f.frame_index, timestamp=f.timestamp
                ),
            )
        return detections

    train = run(seed=2)
    calibrator = PlattCalibrator().fit(
        np.array([d.raw_confidence for d in train]),
        np.array([int(d.is_true_positive) for d in train]),
    )

    graph = build_graph(DemoChatModel())
    results = []
    for event in cluster_into_events(run(seed=1)):
        p_cv = float(calibrator.predict(np.array([event.mean_raw_confidence]))[0])
        results.append((event, graph.invoke({"event": event.model_dump(), "p_cv": p_cv})))

    alerted = [e for e, out in results if out["action"] == "alert"]
    assert alerted and all(e.is_true_positive for e in alerted)
    assert not any(out["action"] == "alert" for e, out in results if not e.is_true_positive)
