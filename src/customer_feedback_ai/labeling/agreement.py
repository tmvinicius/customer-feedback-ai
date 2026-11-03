"""Agreement between two sets of labels: raw agreement and Cohen's kappa.

The metric itself lives in `evaluation.metrics`; it is re-exported here.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from customer_feedback_ai.evaluation.metrics import cohen_kappa


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float | None
    kappa: float | None


def agreement(first: Sequence[str], second: Sequence[str]) -> Agreement:
    n = len(first)
    observed = None if n == 0 else sum(a == b for a, b in zip(first, second, strict=True)) / n
    return Agreement(n=n, observed=observed, kappa=cohen_kappa(first, second))


__all__ = ["Agreement", "agreement", "cohen_kappa"]
