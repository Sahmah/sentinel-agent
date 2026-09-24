"""Is the calibration actually good? Reliability diagram data, Brier score,
and Expected Calibration Error (ECE) — use all three together (skill §5):
the reliability diagram for a visual check, ECE as the scalar to track over
time, Brier score as a sanity check that also rewards sharpness.
"""

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss


def reliability_diagram_data(
    labels: np.ndarray, probs: np.ndarray, *, n_bins: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (fraction_of_positives, mean_predicted_probability) per bin.
    Perfect calibration plots as the diagonal y=x."""
    prob_true, prob_pred = calibration_curve(labels, probs, n_bins=n_bins)
    return prob_true, prob_pred


def brier_score(labels: np.ndarray, probs: np.ndarray) -> float:
    return float(brier_score_loss(labels, probs))


def expected_calibration_error(labels: np.ndarray, probs: np.ndarray, *, n_bins: int = 10) -> float:
    """ECE = sum over bins of (bin weight) * |accuracy(bin) - avg_confidence(bin)|."""
    bins = np.linspace(0, 1, n_bins + 1)
    labels_arr, probs_arr = np.asarray(labels), np.asarray(probs)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:], strict=True):
        mask = (probs_arr > lo) & (probs_arr <= hi)
        if mask.sum() == 0:
            continue
        bin_acc = labels_arr[mask].mean()
        bin_conf = probs_arr[mask].mean()
        ece += (mask.sum() / len(probs_arr)) * abs(bin_acc - bin_conf)
    return float(ece)
