"""Quality of topic and urgency predictions against a labeled set (AGENTS.md, section 8)."""

from collections.abc import Sequence
from typing import Any

from customer_feedback_ai.evaluation.bootstrap import bootstrap_interval
from customer_feedback_ai.evaluation.metrics import macro_f1, per_class_scores, recall_of
from customer_feedback_ai.labeling.taxonomy import URGENCY_LEVELS

HIGH_URGENCY = "alta"


def _interval(
    metric: Any, truth: Sequence[str], pred: Sequence[str], resamples: int, seed: int
) -> dict[str, Any]:
    interval = bootstrap_interval(metric, truth, pred, resamples=resamples, seed=seed)
    return {
        "value": interval.point,
        "ci_low": interval.low,
        "ci_high": interval.high,
        "undefined_resamples": interval.undefined_resamples,
    }


def urgency_macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float | None:
    """Macro-F1 over the three urgency levels, always the same label set."""
    return macro_f1(y_true, y_pred, labels=list(URGENCY_LEVELS))


def evaluate(
    gold_topics: Sequence[str],
    pred_topics: Sequence[str],
    gold_urgency: Sequence[str],
    pred_urgency: Sequence[str],
    *,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    """Topic macro-F1 (main metric) with interval, F1 per class with support,
    urgency macro-F1 with interval and high-urgency recall with its support."""
    return {
        "n": len(gold_topics),
        "topic_macro_f1": _interval(macro_f1, gold_topics, pred_topics, resamples, seed),
        "topic_per_class": {
            score.label: {
                "f1": score.f1,
                "precision": score.precision,
                "recall": score.recall,
                "support": score.support,
            }
            for score in per_class_scores(gold_topics, pred_topics)
        },
        "urgency_macro_f1": _interval(
            urgency_macro_f1, gold_urgency, pred_urgency, resamples, seed
        ),
        "high_urgency_recall": {
            "value": recall_of(gold_urgency, pred_urgency, HIGH_URGENCY),
            "support": sum(label == HIGH_URGENCY for label in gold_urgency),
        },
    }
