"""Bootstrap confidence intervals (AGENTS.md, section 8: 1,000 resamples, 95%).

Items are resampled with replacement; every resample uses the same indices for
all sequences, so a paired comparison of two models keeps their errors aligned.
Intervals use the percentile method. Resamples where a metric is undefined (for
example, a kappa with a single category) are dropped and counted.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Metric = Callable[[Sequence[str], Sequence[str]], float | None]

DEFAULT_RESAMPLES = 1_000
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Interval:
    point: float | None
    low: float | None
    high: float | None
    resamples: int
    undefined_resamples: int
    confidence: float

    def contains(self, value: float) -> bool:
        return self.low is not None and self.high is not None and self.low <= value <= self.high


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of already sorted values."""
    if not sorted_values:
        msg = "quantile of an empty sequence"
        raise ValueError(msg)
    position = q * (len(sorted_values) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _interval(
    point: float | None, values: list[float], undefined: int, resamples: int, confidence: float
) -> Interval:
    if not values:
        return Interval(point, None, None, resamples, undefined, confidence)
    values.sort()
    tail = (1 - confidence) / 2
    return Interval(
        point, quantile(values, tail), quantile(values, 1 - tail), resamples, undefined, confidence
    )


def _indices(n: int, rng: random.Random) -> list[int]:
    return [rng.randrange(n) for _ in range(n)]


def bootstrap_interval(
    metric: Metric,
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Interval:
    """Point estimate of `metric` and its bootstrap percentile interval."""
    if len(y_true) != len(y_pred):
        msg = "label sequences must have the same length"
        raise ValueError(msg)
    point = metric(y_true, y_pred)
    n = len(y_true)
    if n == 0:
        return Interval(point, None, None, resamples, resamples, confidence)
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        idx = _indices(n, rng)
        value = metric([y_true[i] for i in idx], [y_pred[i] for i in idx])
        if value is not None:
            values.append(value)
    return _interval(point, values, resamples - len(values), resamples, confidence)


def paired_bootstrap_difference(
    metric: Metric,
    y_true: Sequence[str],
    pred_a: Sequence[str],
    pred_b: Sequence[str],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Interval:
    """Interval of metric(A) - metric(B) on the same resampled items."""
    if not len(y_true) == len(pred_a) == len(pred_b):
        msg = "label sequences must have the same length"
        raise ValueError(msg)

    def difference(idx: Sequence[int]) -> float | None:
        truth = [y_true[i] for i in idx]
        a = metric(truth, [pred_a[i] for i in idx])
        b = metric(truth, [pred_b[i] for i in idx])
        return None if a is None or b is None else a - b

    n = len(y_true)
    point = difference(range(n)) if n else None
    if n == 0:
        return Interval(point, None, None, resamples, resamples, confidence)
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        value = difference(_indices(n, rng))
        if value is not None:
            values.append(value)
    return _interval(point, values, resamples - len(values), resamples, confidence)
