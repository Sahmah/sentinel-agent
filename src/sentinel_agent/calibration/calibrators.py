"""Post-hoc calibration of a detector's raw confidence scores.

Raw sigmoid/softmax-style scores from a detector are not probabilities — they
are typically overconfident. These wrap the standard techniques (see the
confidence-calibration skill, section 1, for when to use which); this module
has no dependency on the rest of `sentinel_agent` beyond numpy/scikit-learn,
so it can be lifted into its own package later.
"""

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss


class PlattCalibrator:
    """Fits a 1D logistic regression on raw scores. Good default with limited
    calibration data (hundreds of labeled examples, not thousands)."""

    def __init__(self) -> None:
        # Effectively unregularized, as in the original Platt method. sklearn's
        # default L2 penalty (C=1) flattens the slope when raw scores sit in a
        # narrow band (e.g. 0.89-0.93), collapsing every output to the base rate.
        self._model = LogisticRegression(C=1e6)
        self._fitted = False

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "PlattCalibrator":
        self._model.fit(np.asarray(raw_scores).reshape(-1, 1), np.asarray(labels))
        self._fitted = True
        return self

    def predict(self, raw_scores: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("PlattCalibrator must be fit() before predict()")
        return self._model.predict_proba(np.asarray(raw_scores).reshape(-1, 1))[:, 1]


class IsotonicCalibrator:
    """Non-parametric monotonic calibration. More flexible than Platt scaling
    but needs ~1000+ labeled examples or it overfits — prefer Platt scaling
    below that scale."""

    def __init__(self) -> None:
        self._model = IsotonicRegression(out_of_bounds="clip")
        self._fitted = False

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "IsotonicCalibrator":
        self._model.fit(np.asarray(raw_scores), np.asarray(labels))
        self._fitted = True
        return self

    def predict(self, raw_scores: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("IsotonicCalibrator must be fit() before predict()")
        return self._model.predict(np.asarray(raw_scores))


def temperature_scale(logits: np.ndarray, temperature: float) -> np.ndarray:
    """Single-scalar temperature scaling. Preserves the ranking of the raw
    scores exactly — only fixes over/under-confidence, never reorders."""
    return 1.0 / (1.0 + np.exp(-logits / temperature))


def fit_temperature(
    logits: np.ndarray, labels: np.ndarray, *, grid: np.ndarray | None = None
) -> float:
    """Grid-search the temperature that minimizes log loss on held-out data."""
    if grid is None:
        grid = np.linspace(0.05, 5.0, 200)
    losses = [log_loss(labels, temperature_scale(logits, t), labels=[0, 1]) for t in grid]
    return float(grid[int(np.argmin(losses))])
