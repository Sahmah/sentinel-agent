"""Glue between the stages: detections -> calibrated events -> agent decisions.

Shared by `sentinel demo` (synthetic scene) and `sentinel webcam` (live), so
both run exactly the same aggregation, fusion and graph code.
"""

from dataclasses import dataclass

import numpy as np

from sentinel_agent.calibration.calibrators import PlattCalibrator
from sentinel_agent.calibration.metrics import brier_score, expected_calibration_error
from sentinel_agent.detection.base import Detector
from sentinel_agent.detection.classical import ClassicalCVDetector
from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.scenario import generate_scenario, label_detections
from sentinel_agent.events.models import Event


@dataclass(frozen=True)
class Decision:
    event: Event
    p_cv: float
    calibrated: bool  # False when p_cv is the detector's raw score (no labels to fit on)
    state: dict  # final EventState from the graph


@dataclass(frozen=True)
class CalibrationReport:
    n_detections: int
    raw_ece: float
    calibrated_ece: float
    raw_brier: float
    calibrated_brier: float


def synthetic_detections(seed: int, detector: Detector | None = None) -> list[Detection]:
    detector = detector or ClassicalCVDetector()
    detections: list[Detection] = []
    for f in generate_scenario(seed=seed):
        found = detector.detect(
            f.frame, camera_id=f.camera_id, frame_index=f.frame_index, timestamp=f.timestamp
        )
        detections += label_detections(f, found)
    return detections


def _scores_and_labels(detections: list[Detection]) -> tuple[np.ndarray, np.ndarray]:
    labeled = [d for d in detections if d.is_true_positive is not None]
    return (
        np.array([d.raw_confidence for d in labeled]),
        np.array([int(d.is_true_positive) for d in labeled]),
    )


def fit_calibrator(detections: list[Detection]) -> PlattCalibrator:
    scores, labels = _scores_and_labels(detections)
    if len(set(labels.tolist())) < 2:
        raise ValueError("Calibration needs both true and false positives in the labeled set")
    return PlattCalibrator().fit(scores, labels)


def evaluate_calibration(
    calibrator: PlattCalibrator, detections: list[Detection]
) -> CalibrationReport:
    """Score on detections the calibrator was NOT fit on — in-sample ECE is
    misleadingly close to zero."""
    scores, labels = _scores_and_labels(detections)
    calibrated = calibrator.predict(scores)
    return CalibrationReport(
        n_detections=len(scores),
        raw_ece=expected_calibration_error(labels, scores),
        calibrated_ece=expected_calibration_error(labels, calibrated),
        raw_brier=brier_score(labels, scores),
        calibrated_brier=brier_score(labels, calibrated),
    )


def decide(graph, event: Event, calibrator: PlattCalibrator | None = None) -> Decision:
    if calibrator is not None:
        p_cv = float(calibrator.predict(np.array([event.mean_raw_confidence]))[0])
    else:
        p_cv = event.mean_raw_confidence
    event = event.model_copy(update={"calibrated_confidence": p_cv if calibrator else None})
    state = graph.invoke({"event": event.model_dump(), "p_cv": p_cv})
    return Decision(event=event, p_cv=p_cv, calibrated=calibrator is not None, state=state)
