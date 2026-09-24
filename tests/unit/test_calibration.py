import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sentinel_agent.calibration.calibrators import (
    IsotonicCalibrator,
    PlattCalibrator,
    fit_temperature,
    temperature_scale,
)
from sentinel_agent.calibration.fusion import combined_confidence, should_escalate
from sentinel_agent.calibration.llm_confidence import self_consistency_confidence
from sentinel_agent.calibration.metrics import brier_score, expected_calibration_error


def _overconfident_scores(n: int = 400, seed: int = 0):
    """True positive rate rises with score, but much more slowly than the score claims."""
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.7, 0.99, n)
    labels = (rng.uniform(0, 1, n) < (raw - 0.7) / 0.29 * 0.6 + 0.2).astype(int)
    return raw, labels


@pytest.mark.parametrize("calibrator", [PlattCalibrator, IsotonicCalibrator])
def test_calibration_reduces_ece(calibrator):
    raw, labels = _overconfident_scores()
    calibrated = calibrator().fit(raw, labels).predict(raw)
    assert expected_calibration_error(labels, calibrated) < expected_calibration_error(labels, raw)


def test_platt_is_not_flattened_by_a_narrow_score_band():
    # Regression: with sklearn's default L2 penalty every output was the base rate.
    raw = np.array([0.893] * 20 + [0.916] * 20)
    labels = np.array([0] * 20 + [1] * 20)
    probs = PlattCalibrator().fit(raw, labels).predict(np.array([0.893, 0.916]))
    assert probs[0] < 0.1 and probs[1] > 0.9


@pytest.mark.parametrize("calibrator", [PlattCalibrator, IsotonicCalibrator])
def test_predict_before_fit_raises(calibrator):
    with pytest.raises(RuntimeError):
        calibrator().predict(np.array([0.5]))


@given(
    st.lists(st.floats(-20, 20, allow_nan=False), min_size=2, max_size=50),
    st.floats(0.05, 10),
)
def test_temperature_scaling_preserves_ranking(logits, temperature):
    arr = np.array(logits)
    order = np.argsort(arr, kind="stable")
    scaled = temperature_scale(arr, temperature)
    assert np.all(np.diff(scaled[order]) >= 0)


def test_fit_temperature_softens_overconfident_logits():
    rng = np.random.default_rng(1)
    true_logits = rng.normal(0, 1.5, 2000)
    labels = (rng.uniform(0, 1, 2000) < 1 / (1 + np.exp(-true_logits))).astype(int)
    assert fit_temperature(true_logits * 3, labels) > 1.5


def test_metrics_perfect_and_worst_case():
    labels = np.array([0, 1, 0, 1])
    assert brier_score(labels, labels.astype(float)) == 0.0
    assert brier_score(labels, 1 - labels.astype(float)) == 1.0
    assert expected_calibration_error(labels, np.array([0.01, 0.99, 0.01, 0.99])) < 0.02


def test_self_consistency_agreement_rate():
    answers = iter(["high", "high", "low"])
    top, agreement = self_consistency_confidence(lambda: next(answers), n=3)
    assert top == "high"
    assert agreement == pytest.approx(2 / 3)
    with pytest.raises(ValueError):
        self_consistency_confidence(lambda: "x", n=0)


def test_combined_confidence_weighting():
    assert combined_confidence(1.0, 0.0, w_cv=0.75) == 0.75


@pytest.mark.parametrize(
    ("p_cv", "p_llm", "escalate", "disagreement"),
    [
        (0.9, 0.85, False, False),  # corroborating and confident
        (0.5, 0.5, True, False),  # agree, but not confident enough
        (0.95, 0.3, True, True),  # individually fine-looking, but they disagree
    ],
)
def test_should_escalate(p_cv, p_llm, escalate, disagreement):
    result = should_escalate(p_cv, p_llm)
    assert result.should_escalate is escalate
    assert result.disagreement is disagreement
