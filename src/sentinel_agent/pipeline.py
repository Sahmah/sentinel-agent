"""Glue between the stages: detections -> calibrated events -> agent decisions.

Shared by `sentinel demo` (synthetic scene) and `sentinel webcam` (live), so
both run exactly the same aggregation, fusion and graph code, and store the
same records.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from sentinel_agent.calibration.calibrators import PlattCalibrator
from sentinel_agent.calibration.metrics import brier_score, expected_calibration_error
from sentinel_agent.detection.base import Detector
from sentinel_agent.detection.classical import ClassicalCVDetector
from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.scenario import generate_scenario, label_detections
from sentinel_agent.events.models import Event
from sentinel_agent.storage.base import EventFilter, EventRecord, Storage


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


def synthetic_scene(
    seed: int, detector: Detector | None = None
) -> tuple[dict[int, np.ndarray], list[Detection]]:
    """The rendered frames (by index, for snapshots) and their labeled detections."""
    detector = detector or ClassicalCVDetector()
    frames: dict[int, np.ndarray] = {}
    detections: list[Detection] = []
    for f in generate_scenario(seed=seed):
        frames[f.frame_index] = f.frame
        found = detector.detect(
            f.frame, camera_id=f.camera_id, frame_index=f.frame_index, timestamp=f.timestamp
        )
        detections += label_detections(f, found)
    return frames, detections


def synthetic_detections(seed: int, detector: Detector | None = None) -> list[Detection]:
    return synthetic_scene(seed, detector)[1]


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


def decide(
    graph,
    event: Event,
    calibrator: PlattCalibrator | None = None,
    snapshot_path: str | None = None,
) -> Decision:
    if calibrator is not None:
        p_cv = float(calibrator.predict(np.array([event.mean_raw_confidence]))[0])
    else:
        p_cv = event.mean_raw_confidence
    event = event.model_copy(update={"calibrated_confidence": p_cv if calibrator else None})
    state = graph.invoke(
        {"event": event.model_dump(), "p_cv": p_cv, "snapshot_path": snapshot_path}
    )
    return Decision(event=event, p_cv=p_cv, calibrated=calibrator is not None, state=state)


def to_record(
    d: Decision,
    *,
    run_id: str,
    source: str,
    run_started_at: datetime,
    snapshot: str | None = None,
) -> EventRecord:
    """Event timestamps are seconds into the run; anchor them to wall-clock time."""
    e, s = d.event, d.state
    return EventRecord(
        id=e.id,
        run_id=run_id,
        source=source,
        camera_id=e.camera_id,
        label=e.label,
        occurred_at=run_started_at + timedelta(seconds=e.start_ts),
        duration_seconds=round(e.end_ts - e.start_ts, 3),
        detection_count=e.detection_count,
        entered_restricted_zone=e.entered_restricted_zone,
        p_cv=d.p_cv,
        p_cv_calibrated=d.calibrated,
        p_cv_raw=e.mean_raw_confidence,
        llm_confidence=s.get("llm_confidence"),
        combined_confidence=s.get("combined_confidence"),
        disagreement=s.get("disagreement", False),
        severity=s.get("severity"),
        action=s["action"],
        reasoning=s.get("reasoning"),
        confidence_basis=s.get("confidence_basis"),
        triage_reason=s.get("triage_reason"),
        is_true_positive=e.is_true_positive,
        snapshot=snapshot,
    )


def calibrator_from_reviews(
    storage: Storage, camera_id: str, *, min_per_class: int = 5, max_records: int = 5000
) -> tuple[PlattCalibrator | None, int]:
    """Fit Platt scaling on this camera's human-reviewed events: the live
    equivalent of the synthetic ground truth. Returns (None, n) until there are
    at least `min_per_class` verdicts of each kind, because a calibrator fit on
    a handful of one-sided labels is worse than none."""
    scores: list[float] = []
    labels: list[int] = []
    seen, cursor = 0, None
    while seen < max_records:
        page = storage.query(EventFilter(camera_id=camera_id), limit=100, cursor=cursor)
        seen += len(page.events)
        for r in page.events:
            if r.review is not None and r.p_cv_raw is not None:
                scores.append(r.p_cv_raw)
                labels.append(int(r.review == "real"))
        cursor = page.next_cursor
        if cursor is None:
            break
    n_real = sum(labels)
    if min(n_real, len(labels) - n_real) < min_per_class:
        return None, len(labels)
    return PlattCalibrator().fit(np.array(scores), np.array(labels)), len(labels)
