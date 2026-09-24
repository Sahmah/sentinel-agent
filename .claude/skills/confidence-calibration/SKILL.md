---
name: confidence-calibration
description: Practical techniques for calibrating and combining CV detection confidence with LLM certainty signals in a multi-agent pipeline, used in the Sentinel Agent project
---

# Confidence Calibration for a CV → LLM Agent Pipeline

Scope note (read first): this skill implements a **simplified, honest** approach to
combining a calibrated detector score with an LLM certainty signal for a
human-escalation decision. It is deliberately *not* an implementation of the
2026 multi-agent uncertainty-propagation literature (trajectory-adapted UQ,
counterfactual-graph calibration). Those are cited in "Where the state of the
art goes further" so we don't overclaim novelty.

## 1. Calibrating the CV detector's raw confidence

Raw sigmoid/softmax scores from object detectors are *not* probabilities —
they're typically overconfident. Three standard post-hoc calibration methods
(scikit-learn docs: https://scikit-learn.org/stable/modules/calibration.html):

- **Platt scaling** (`method="sigmoid"`): fits a 1D logistic regression on the
  score. Good default when you have limited calibration data or the
  miscalibration is roughly sigmoid-shaped (e.g. neural net logits).
- **Isotonic regression**: fits a non-parametric monotonic step function.
  More flexible, corrects any monotonic distortion, but needs more data
  (~1000+ labeled examples) or it overfits
  (https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV.html).
- **Temperature scaling**: single scalar `T` dividing the logit before
  softmax; the standard choice for neural network calibration (Guo et al.
  2017, *On Calibration of Modern Neural Networks*). Preserves the model's
  argmax/ranking exactly, so it's the least invasive option — a good fit when
  you only want to fix over/under-confidence, not reorder detections.

### Minimal implementation

Detectors (YOLO, etc.) don't expose an sklearn `Estimator`, so
`CalibratedClassifierCV` (which wraps a fitted classifier) doesn't apply
directly — calibrate the score array yourself:

```python
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

# raw_scores: detector confidence in [0,1], shape (n,)
# labels: 1 if the detection was a true positive (human-verified), else 0

# --- Platt scaling ---
platt = LogisticRegression()
platt.fit(raw_scores.reshape(-1, 1), labels)
calibrated = platt.predict_proba(raw_scores.reshape(-1, 1))[:, 1]

# --- Isotonic regression ---
iso = IsotonicRegression(out_of_bounds="clip")
iso.fit(raw_scores, labels)
calibrated = iso.predict(raw_scores)


# --- Temperature scaling (from-scratch, on logits not scores) ---
def temperature_scale(logits: np.ndarray, T: float) -> np.ndarray:
    return 1 / (1 + np.exp(-logits / T))


def fit_temperature(logits, labels, T_grid=np.linspace(0.05, 5.0, 200)):
    from sklearn.metrics import log_loss

    losses = [log_loss(labels, temperature_scale(logits, T)) for T in T_grid]
    return T_grid[int(np.argmin(losses))]
```

Always fit calibration on a **held-out** split, never on the data the
detector was trained/thresholded on — otherwise you calibrate to noise.

**Which to pick for Sentinel Agent**: start with Platt scaling — the
detector's escalation-relevant calibration set (human-reviewed true/false
positives) will likely be in the hundreds, not thousands, and isotonic
regression overfits at that scale
(https://fastml.com/classifier-calibration-with-platts-scaling-and-isotonic-regression/).
Move to isotonic once the labeled set grows past ~1–2k examples.

## 2. Getting a usable certainty signal from Claude (Bedrock)

### Verbalized confidence prompting

Ask for a discrete or numeric self-rating *and* a justification, not just a
number — this is the standard "verbalized confidence" elicitation pattern:

```python
SYSTEM = """You are analyzing a security event. After your reasoning, output
a JSON object: {"decision": "...", "confidence": <0-100>,
"confidence_basis": "<one sentence: what evidence would change your mind>"}.
Confidence must reflect your actual uncertainty about the CLAIM, not how
fluent your explanation sounds."""
```

### Known caveats (cite these in any design doc, don't hide them)

- Verbalized confidence from instruct-tuned LLMs is systematically
  overconfident — models cluster near 90–100% regardless of correctness
  ("ceiling effect"), even though internal hidden-state probes carry more
  calibration signal than the verbalized number
  (https://arxiv.org/html/2604.24070v1, "Distilling Self-Consistency into
  Verbal Confidence"; https://arxiv.org/pdf/2605.27752, "Asking Is Not
  Enough: Protocol Sensitivity in LLM Confidence Calibration" — the exact
  elicitation wording measurably changes the result).
- Log-probability-based confidence (token logprobs from the API) is a
  different signal from verbalized confidence and the two often disagree;
  Bedrock's Claude Messages API can return `logprobs` for some
  configurations, but for a multi-step agentic decision (not a single
  token/label), verbalized or self-consistency confidence is usually more
  meaningful than raw token logprob.
- **Self-consistency / sampling ensemble** is a stronger alternative:
  sample the same decision N times (temperature > 0) and use agreement rate
  as the confidence proxy. Recent work finds even **2 samples** meaningfully
  improve calibration over asking once
  (https://openreview.net/forum?id=66D3rZrNjV, "Two Samples Are Enough:
  Verbal Confidence Meets Self-Consistency in Reasoning LLMs").

```python
from collections import Counter


def self_consistency_confidence(agent_call, event, n=3, temperature=0.7):
    decisions = [agent_call(event, temperature=temperature) for _ in range(n)]
    counts = Counter(d["decision"] for d in decisions)
    top_decision, top_count = counts.most_common(1)[0]
    agreement = top_count / n  # naive confidence proxy
    return top_decision, agreement
```

This costs N× the Bedrock calls — for Sentinel Agent, reserve it for
mid-confidence cases (e.g. verbalized confidence in a 40–75 "gray zone")
rather than running it on every event.

## 3. Combining the two signals into an escalate/don't-escalate decision

Treat the calibrated detector probability `p_cv` and the LLM certainty
`p_llm` (rescaled to [0,1]) as **two independent, heterogeneous pieces of
evidence**, not a single joint model — we don't have paired training labels
to fit a real fusion model, so honesty here matters more than sophistication.

### Simplified combination rule

```python
def combined_confidence(p_cv: float, p_llm: float, w_cv: float = 0.5) -> float:
    """Weighted linear combination. w_cv is a tunable prior on which
    signal you trust more; start at 0.5 and adjust from escalation review
    outcomes."""
    return w_cv * p_cv + (1 - w_cv) * p_llm


def should_escalate(p_cv, p_llm, threshold=0.6, disagreement_gap=0.35):
    combined = combined_confidence(p_cv, p_llm)
    # Escalate on low combined confidence OR when the two signals
    # strongly disagree (that disagreement is itself informative —
    # it means the detector and the reasoning agent are not corroborating
    # each other, which is a good escalation trigger even if each score
    # individually looks fine).
    disagree = abs(p_cv - p_llm) > disagreement_gap
    return combined < threshold or disagree
```

The disagreement check is the one piece of "cheap sophistication" worth
including: independent-evidence fusion is only valid when the sources are
actually uncorrelated, and a large gap between `p_cv` and `p_llm` is a signal
that assumption may be breaking down for this specific event — so route it to
a human rather than silently averaging it away.

### Where the state of the art goes further (and why we're not building it)

The two signals above are treated as static, independent numbers. Real
multi-agent UQ research treats confidence as something that propagates and
correlates across a *trajectory* of agent steps:

- **Trajectory-adapted UQ** (Bouchard & Chauhan, 2026,
  https://arxiv.org/abs/2608.11552, "Beyond Single-Turn Confidence") shows
  that single-turn UQ methods (token-probability, self-consistency,
  reflexive self-assessment) transfer unevenly to multi-turn/tool-use agent
  trajectories, and that black-box resampled-trajectory consistency is often
  the strongest signal — much more expensive than our single-shot approach.
- **Counterfactual-graph calibration** (Huang et al., 2026,
  https://arxiv.org/abs/2605.30653, "Counterfactual Graph for Multi-Agent LLM
  Calibration", CAGE-Cal) shows that when multiple agents communicate,
  naive agreement-counting is unsound because communication induces
  correlated failures and false consensus — exactly the independence
  assumption our simplified weighted-combination relies on. CAGE-Cal
  compares the observed agent-interaction graph to a counterfactual
  no-communication graph to correct for this.
- General taxonomy: https://arxiv.org/html/2609.07395 ("Uncertainty
  Quantification for LLM Agents: A Taxonomy, an Evaluation Protocol, and an
  Empirical Study").

Sentinel Agent has one detector and one reasoning agent (not a
multi-agent-communicating swarm), so the independence assumption is a much
smaller stretch than in the multi-agent case — but it is still an
assumption, not a proven property, and should be stated as such in any
README/portfolio writeup.

## 4. What to depend on vs. implement from scratch

| Use a library for | Implement from scratch for |
|---|---|
| Isotonic regression (`sklearn.isotonic.IsotonicRegression`) | Temperature scaling (it's ~10 lines and shows you understand it) |
| Platt scaling (`sklearn.linear_model.LogisticRegression`, or `CalibratedClassifierCV` if you have a real sklearn estimator) | The escalation-decision combination rule (it's the project's actual contribution — don't hide it behind a black box) |
| ECE / Brier score / reliability curves (`sklearn.calibration.calibration_curve`, `sklearn.metrics.brier_score_loss`) | Self-consistency sampling loop over Bedrock calls (there's no good generic library for this against a specific agent's decision schema) |
| `numpy` for array math | The disagreement/gray-zone routing logic |

Rationale: for a portfolio piece, depending on scikit-learn for the *well-established,
solved* pieces (isotonic/Platt/ECE) is honest engineering judgment, not
laziness — reimplementing isotonic regression correctly (PAVA algorithm) adds
no pedagogical value. The combination logic and Bedrock-facing prompting are
where the project's actual design decisions live, so those should be visible,
readable code.

## 5. Evaluating whether calibration is actually good

```python
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss
import numpy as np

# Reliability diagram data: bins of predicted probability vs observed frequency
prob_true, prob_pred = calibration_curve(labels, calibrated_scores, n_bins=10)
# Plot prob_pred (x) vs prob_true (y); perfect calibration = diagonal y=x
# (https://scikit-learn.org/stable/auto_examples/calibration/plot_calibration_curve.html)

# Brier score: mean squared error between predicted prob and outcome (0 or 1)
# Lower is better, but note it conflates calibration with discrimination/refinement —
# don't use it alone (https://scikit-learn.org/stable/modules/calibration.html).
brier = brier_score_loss(labels, calibrated_scores)


def expected_calibration_error(labels, probs, n_bins=10):
    """ECE = sum over bins of (bin weight) * |accuracy(bin) - avg_confidence(bin)|"""
    bins = np.linspace(0, 1, n_bins + 1)
    labels, probs = np.asarray(labels), np.asarray(probs)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (probs > lo) & (probs <= hi)
        if mask.sum() == 0:
            continue
        bin_acc = labels[mask].mean()
        bin_conf = probs[mask].mean()
        ece += (mask.sum() / len(probs)) * abs(bin_acc - bin_conf)
    return ece
```

Use all three together: the reliability diagram for a visual/qualitative
check, ECE as the single scalar to track over time (e.g. per model release),
and Brier score as a sanity check that also rewards sharpness (confident and
correct beats vague-but-technically-calibrated).

## 6. Novelty check (verified 2026-09)

Searched for an existing generic, pip-installable "multi-agent confidence
calibration" / "agent uncertainty quantification" library. None does what
Sentinel Agent needs (calibrate a CV detector + fuse with an LLM agent's
certainty + drive a human-escalation threshold):

- **LM-Polygraph** (https://github.com/IINemo/lm-polygraph, `pip install
  lm-polygraph`) — real, maintained, but scoped to single-LLM text-generation
  uncertainty/hallucination detection, not CV+LLM signal fusion.
- **uncertainty-toolbox** (https://github.com/uncertainty-toolbox/uncertainty-toolbox)
  — generic regression-model UQ/calibration, not agent- or fusion-specific.
- Everything else found (CAGE-Cal, AUQ, UA-ChatDev, SAUP, UProp) is
  academic-paper code, not a packaged, generic OSS library.

The "no accessible OSS library for this specific gap" claim holds.
