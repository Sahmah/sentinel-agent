"""Getting a usable certainty signal out of an LLM.

Verbalized confidence (asking the model to self-rate) is the cheap default,
but it's known to be systematically overconfident (models cluster near
90-100% regardless of correctness — the "ceiling effect"). Self-consistency
sampling — asking the same question N times and using agreement rate as the
confidence proxy — is a stronger, still-cheap alternative; even N=2 samples
meaningfully improves calibration over asking once. See the
confidence-calibration skill, section 2, for citations.
"""

from collections import Counter
from collections.abc import Callable


def self_consistency_confidence[T](
    agent_call: Callable[[], T],
    *,
    n: int = 3,
) -> tuple[T, float]:
    """Call `agent_call` `n` times (it should itself vary temperature/sampling)
    and return (most common result, agreement rate) as a confidence proxy.

    Costs n times the LLM calls — reserve this for mid-confidence "gray zone"
    cases rather than running it on every event.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    results = [agent_call() for _ in range(n)]
    counts = Counter(results)
    top_result, top_count = counts.most_common(1)[0]
    agreement = top_count / n
    return top_result, agreement
