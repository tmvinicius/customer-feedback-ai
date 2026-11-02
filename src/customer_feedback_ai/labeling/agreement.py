"""Agreement between two sets of labels: raw agreement and Cohen's kappa."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float | None
    kappa: float | None


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Cohen's kappa. None when undefined: no pairs, or one category everywhere."""
    if len(first) != len(second):
        msg = "label sequences must have the same length"
        raise ValueError(msg)
    n = len(first)
    if n == 0:
        return None
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    first_counts, second_counts = Counter(first), Counter(second)
    expected = sum(first_counts[c] * second_counts[c] for c in first_counts) / (n * n)
    if expected == 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def agreement(first: Sequence[str], second: Sequence[str]) -> Agreement:
    n = len(first)
    observed = None if n == 0 else sum(a == b for a, b in zip(first, second, strict=True)) / n
    return Agreement(n=n, observed=observed, kappa=cohen_kappa(first, second))
