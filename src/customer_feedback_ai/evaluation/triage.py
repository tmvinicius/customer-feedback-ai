"""Rules that pick C4 and C5 among the local LLM candidates (docs/decisions.md, 2026-11-04).

| Slot          | Candidates                 | Rule                                              |
| ------------- | -------------------------- | ------------------------------------------------- |
| C4 (smaller)  | Gemma 4 E4B x Qwen 3.5 4B  | Topic macro-F1 on gold_dev; tie broken by speed   |
| C5 (larger)   | Qwen 3.5 9B x Llama 3.1 8B | Topic macro-F1 among those viable on the machine  |

C4 is a tie when the 95% paired-bootstrap interval of the macro-F1 difference
contains zero; the lower p50 latency then wins. In C5, a candidate is viable when
it answers the whole triage on the maintainer's machine (6 GB of VRAM, with some
layers on the CPU when needed) without runtime errors; the share of the model in
VRAM is recorded, not required. Non-viable candidates are dropped first; when
none is viable, C5 is cut. An exact macro-F1 tie in C5 goes to the lower p50 latency.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from customer_feedback_ai.evaluation.bootstrap import (
    DEFAULT_RESAMPLES,
    Interval,
    Metric,
    paired_bootstrap_difference,
)
from customer_feedback_ai.evaluation.metrics import macro_f1


@dataclass(frozen=True)
class Candidate:
    name: str
    topic_predictions: tuple[str, ...]
    latency_p50_s: float
    viable: bool = True
    vram_share: float | None = None


@dataclass(frozen=True)
class TriageDecision:
    slot: str
    winner: str | None
    reason: str
    macro_f1: dict[str, float | None]
    difference: Interval | None = None


def _scores(
    y_true: Sequence[str], candidates: Sequence[Candidate], metric: Metric
) -> dict[str, float | None]:
    return {c.name: metric(y_true, c.topic_predictions) for c in candidates}


def choose_smaller(
    y_true: Sequence[str],
    first: Candidate,
    second: Candidate,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
    metric: Metric = macro_f1,
) -> TriageDecision:
    """C4: higher topic macro-F1 wins unless the paired interval contains zero."""
    scores = _scores(y_true, (first, second), metric)
    difference = paired_bootstrap_difference(
        metric,
        y_true,
        first.topic_predictions,
        second.topic_predictions,
        resamples=resamples,
        seed=seed,
    )
    if difference.point is None or difference.contains(0.0):
        winner = min((first, second), key=lambda c: c.latency_p50_s)
        reason = (
            "tie: the 95% interval of the macro-F1 difference contains zero; "
            f"lower p50 latency wins ({winner.latency_p50_s:.3f}s)"
        )
    else:
        winner = first if difference.point > 0 else second
        reason = "higher topic macro-F1, with the 95% interval of the difference excluding zero"
    return TriageDecision("C4", winner.name, reason, scores, difference)


def choose_larger(
    y_true: Sequence[str], candidates: Sequence[Candidate], metric: Metric = macro_f1
) -> TriageDecision:
    """C5: drop candidates that are not viable on the machine, then take the higher macro-F1."""
    scores = _scores(y_true, candidates, metric)
    viable = [c for c in candidates if c.viable]
    if not viable:
        return TriageDecision(
            "C5", None, "no candidate is viable on the machine; C5 is cut", scores
        )
    best = max(viable, key=lambda c: (scores[c.name] or 0.0, -c.latency_p50_s))
    top = scores[best.name] or 0.0
    tied = [c for c in viable if (scores[c.name] or 0.0) == top]
    dropped = sorted(c.name for c in candidates if not c.viable)
    if len(tied) > 1:
        reason = (
            "exact tie on topic macro-F1 among viable candidates; lower p50 latency wins "
            f"({best.latency_p50_s:.3f}s)"
        )
    else:
        reason = "higher topic macro-F1 among candidates viable on the machine"
    if dropped:
        reason += f"; dropped as not viable: {dropped}"
    return TriageDecision("C5", best.name, reason, scores)
