"""Score the reasoning LLM against synthetic ground truth (`sentinel eval-llm`).

The synthetic scenes know which events are real, so any backend can be graded
on the question that matters for fusion: does `p_llm` separate real events from
detector artifacts, and is it calibrated? Numbers, not eyeballing, decide
whether a prompt change or a model swap helped.

Only events that pass triage are scored: the rest never reach the LLM.
"""

import time
from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import roc_auc_score

from sentinel_agent.agent.graph import triage
from sentinel_agent.calibration.calibrators import PlattCalibrator
from sentinel_agent.calibration.metrics import brier_score, expected_calibration_error
from sentinel_agent.events.aggregator import cluster_into_events
from sentinel_agent.pipeline import decide, synthetic_detections


@dataclass(frozen=True)
class EventResult:
    seed: int
    label: str
    detection_count: int
    in_zone: bool
    is_real: bool
    p_llm: float | None  # None when the reply could not be parsed
    severity: str | None
    action: str
    seconds: float


@dataclass
class EvalReport:
    results: list[EventResult] = field(default_factory=list)

    @property
    def parsed(self) -> list[EventResult]:
        return [r for r in self.results if r.p_llm is not None]

    def metrics(self) -> dict[str, float | int | None]:
        parsed = self.parsed
        labels = np.array([int(r.is_real) for r in parsed])
        probs = np.array([r.p_llm for r in parsed], dtype=float)
        both_classes = len(set(labels.tolist())) == 2
        real = [r for r in self.results if r.is_real]
        false = [r for r in self.results if not r.is_real]
        return {
            "events": len(self.results),
            "real": len(real),
            "parse_failures": len(self.results) - len(parsed),
            "auroc": float(roc_auc_score(labels, probs)) if both_classes else None,
            "ece": expected_calibration_error(labels, probs) if parsed else None,
            "brier": brier_score(labels, probs) if parsed else None,
            "mean_p_llm_real": _mean([r.p_llm for r in real if r.p_llm is not None]),
            "mean_p_llm_false": _mean([r.p_llm for r in false if r.p_llm is not None]),
            "real_alerted": sum(r.action == "alert" for r in real),
            "false_alerted": sum(r.action == "alert" for r in false),
            "human_review": sum(r.action == "human_review" for r in self.results),
            "median_seconds": float(np.median([r.seconds for r in self.results]))
            if self.results
            else None,
        }


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def evaluate_llm(
    graph, seeds: list[int], calibrator: PlattCalibrator | None = None, *, progress=None
) -> EvalReport:
    """Run the full graph on every triage-passing event of the given synthetic
    scenes. `progress(result)` is called after each event, for live output."""
    report = EvalReport()
    for seed in seeds:
        for event in cluster_into_events(synthetic_detections(seed)):
            if not triage({"event": event.model_dump()})["triage_passed"]:
                continue
            started = time.monotonic()
            d = decide(graph, event, calibrator)
            result = EventResult(
                seed=seed,
                label=event.label,
                detection_count=event.detection_count,
                in_zone=event.entered_restricted_zone,
                is_real=bool(event.is_true_positive),
                p_llm=None if d.state.get("reasoning_failed") else d.state.get("llm_confidence"),
                severity=d.state.get("severity"),
                action=d.state["action"],
                seconds=time.monotonic() - started,
            )
            report.results.append(result)
            if progress is not None:
                progress(result)
    return report
