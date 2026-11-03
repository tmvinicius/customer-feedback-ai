"""Rules that pick C4 and C5 among the local LLM candidates (docs/decisions.md, 2026-11-04).

| Slot          | Candidates                 | Rule                                              |
| ------------- | -------------------------- | ------------------------------------------------- |
| C4 (smaller)  | Gemma 4 E4B x Qwen 3.5 4B  | Topic macro-F1 on gold_dev; tie broken by speed   |
| C5 (larger)   | Qwen 3.5 9B x Llama 3.1 8B | Topic macro-F1 among those that fit 6 GB VRAM     |

C4 is a tie when the 95% paired-bootstrap interval of the macro-F1 difference
contains zero; the lower p50 latency then wins. In C5, candidates that do not
fit are dropped first; when none fits, C5 is cut.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from customer_feedback_ai.evaluation.bootstrap import (
    DEFAULT_RESAMPLES,
    Interval,
    paired_bootstrap_difference,
)
from customer_feedback_ai.evaluation.metrics import macro_f1


@dataclass(frozen=True)
class Candidate:
    name: str
    topic_predictions: tuple[str, ...]
    latency_p50_s: float
    fits_in_vram: bool = True


@dataclass(frozen=True)
class TriageDecision:
    slot: str
    winner: str | None
    reason: str
    macro_f1: dict[str, float | None]
    difference: Interval | None = None


def _scores(y_true: Sequence[str], candidates: Sequence[Candidate]) -> dict[str, float | None]:
    return {c.name: macro_f1(y_true, c.topic_predictions) for c in candidates}


def choose_smaller(
    y_true: Sequence[str],
    first: Candidate,
    second: Candidate,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> TriageDecision:
    """C4: higher topic macro-F1 wins unless the paired interval contains zero."""
    scores = _scores(y_true, (first, second))
    difference = paired_bootstrap_difference(
        macro_f1,
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


def choose_larger(y_true: Sequence[str], candidates: Sequence[Candidate]) -> TriageDecision:
    """C5: drop candidates that do not fit in VRAM, then take the higher topic macro-F1."""
    scores = _scores(y_true, candidates)
    fitting = [c for c in candidates if c.fits_in_vram]
    if not fitting:
        return TriageDecision("C5", None, "no candidate fits in VRAM; C5 is cut", scores)
    best = max(fitting, key=lambda c: (scores[c.name] or 0.0, -c.latency_p50_s))
    dropped = sorted(c.name for c in candidates if not c.fits_in_vram)
    reason = "higher topic macro-F1 among candidates that fit in VRAM"
    if dropped:
        reason += f"; dropped for not fitting: {dropped}"
    return TriageDecision("C5", best.name, reason, scores)
