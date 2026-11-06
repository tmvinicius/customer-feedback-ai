"""Logistic-regression heads shared by C1 (TF-IDF) and C2 (Serafim embeddings).

Each output (topic, urgency) gets its own classifier. The regularization C comes
from a grid and is chosen on `silver_val` by macro-F1; ties keep the earlier,
smaller C (stronger regularization). Never tuned on `gold_dev` or `test`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sklearn.linear_model import LogisticRegression

from customer_feedback_ai.evaluation.metrics import macro_f1


class ConstantHead:
    """Stand-in classifier when the training labels have a single class."""

    def __init__(self, label: str):
        self.label = label

    def predict(self, features: Any) -> list[str]:
        return [self.label] * features.shape[0]


@dataclass(frozen=True)
class HeadChoice:
    classifier: Any
    c: float | None
    val_macro_f1: dict[str, float | None] = field(default_factory=dict)


def fit_logreg_head(
    train_x: Any,
    train_y: Sequence[str],
    val_x: Any | None,
    val_y: Sequence[str] | None,
    *,
    grid: Sequence[float],
    class_weight: Literal["balanced"] | None,
    max_iter: int,
    seed: int,
) -> HeadChoice:
    if len(set(train_y)) < 2:
        return HeadChoice(ConstantHead(train_y[0]), None)
    has_val = val_x is not None and val_y is not None and len(val_y) > 0
    best: tuple[float, float, Any] | None = None
    scores: dict[str, float | None] = {}
    for c in grid if has_val else grid[:1]:
        clf = LogisticRegression(
            C=c, class_weight=class_weight, max_iter=max_iter, random_state=seed
        ).fit(train_x, list(train_y))
        score = macro_f1(val_y, list(clf.predict(val_x))) if has_val and val_y else None
        scores[str(c)] = score
        if best is None or (score or 0.0) > best[0]:
            best = (score or 0.0, c, clf)
    assert best is not None
    return HeadChoice(best[2], best[1], scores)


def predict_labels(head: Any, features: Any) -> list[str]:
    return [str(label) for label in head.predict(features)]
