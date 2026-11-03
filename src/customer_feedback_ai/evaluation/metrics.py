"""Classification and agreement metrics (AGENTS.md, section 8).

Plain Python on purpose: the sets are small (150 to 350 gold items), and the
formulas stay readable and testable against hand-computed values.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

KappaWeights = Literal["linear", "quadratic"]


@dataclass(frozen=True)
class ClassScores:
    label: str
    precision: float
    recall: float
    f1: float
    support: int


def _check_pairs(first: Sequence[str], second: Sequence[str]) -> None:
    if len(first) != len(second):
        msg = "label sequences must have the same length"
        raise ValueError(msg)


def per_class_scores(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None
) -> list[ClassScores]:
    """Precision, recall, F1 and support per label.

    By default the labels are those present in either sequence, as in
    scikit-learn. A label never predicted has precision 0; a label absent from
    `y_true` has recall 0.
    """
    _check_pairs(y_true, y_pred)
    chosen = sorted(set(y_true) | set(y_pred)) if labels is None else list(labels)
    scores = []
    for label in chosen:
        tp = sum(t == label and p == label for t, p in zip(y_true, y_pred, strict=True))
        fp = sum(t != label and p == label for t, p in zip(y_true, y_pred, strict=True))
        fn = sum(t == label and p != label for t, p in zip(y_true, y_pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(ClassScores(label, precision, recall, f1, tp + fn))
    return scores


def macro_f1(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None
) -> float | None:
    """Unweighted mean of the per-label F1. None when there is nothing to score."""
    scores = per_class_scores(y_true, y_pred, labels)
    if not scores:
        return None
    return sum(score.f1 for score in scores) / len(scores)


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float | None:
    _check_pairs(y_true, y_pred)
    if not y_true:
        return None
    return sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true)


def recall_of(y_true: Sequence[str], y_pred: Sequence[str], label: str) -> float | None:
    """Recall of one label, None when the label never occurs in `y_true`."""
    _check_pairs(y_true, y_pred)
    support = sum(t == label for t in y_true)
    if support == 0:
        return None
    hits = sum(t == label and p == label for t, p in zip(y_true, y_pred, strict=True))
    return hits / support


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Cohen's kappa. None when undefined: no pairs, or one category everywhere."""
    _check_pairs(first, second)
    n = len(first)
    if n == 0:
        return None
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    first_counts, second_counts = Counter(first), Counter(second)
    expected = sum(first_counts[c] * second_counts[c] for c in first_counts) / (n * n)
    if expected == 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def weighted_kappa(
    first: Sequence[str],
    second: Sequence[str],
    order: Sequence[str],
    weights: KappaWeights = "linear",
) -> float | None:
    """Weighted Cohen's kappa for ordinal labels, with disagreement weights.

    The weight of a pair of categories at positions i and j is |i - j| / (k - 1)
    (linear) or its square (quadratic). None when undefined.
    """
    _check_pairs(first, second)
    unknown = (set(first) | set(second)) - set(order)
    if unknown:
        msg = f"labels outside the ordinal scale {list(order)}: {sorted(unknown)}"
        raise ValueError(msg)
    n, k = len(first), len(order)
    if n == 0 or k < 2:
        return None
    index = {label: i for i, label in enumerate(order)}

    def weight(i: int, j: int) -> float:
        distance = abs(i - j) / (k - 1)
        return distance if weights == "linear" else distance**2

    first_counts, second_counts = Counter(first), Counter(second)
    observed = sum(weight(index[a], index[b]) for a, b in zip(first, second, strict=True)) / n
    expected = sum(
        weight(index[a], index[b]) * first_counts[a] * second_counts[b]
        for a in order
        for b in order
    ) / (n * n)
    if expected == 0.0:
        return None
    return 1.0 - observed / expected
