"""Silver agreement criterion, the M2 acceptance rule (docs/decisions.md, 2026-11-04).

Labels from the LLM chosen to label the silver set are compared with the human
`gold_dev` labels:

| Metric                           | Accept  | Alert       | Reject      |
| -------------------------------- | ------- | ----------- | ----------- |
| Topic kappa (Cohen)              | >= 0.60 | 0.50-0.59   | < 0.50      |
| Urgency kappa, linear weights    | >= 0.50 | 0.40-0.49   | < 0.40      |
| High-urgency recall              | report  | alert < 0.80 | never rejects |

The point estimate decides; the 95% bootstrap interval and the supports are
always reported. The worse band of topic and urgency is the overall band.
"""

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from customer_feedback_ai.evaluation.bootstrap import Interval, bootstrap_interval
from customer_feedback_ai.evaluation.metrics import (
    KappaWeights,
    cohen_kappa,
    recall_of,
    weighted_kappa,
)
from customer_feedback_ai.labeling.taxonomy import URGENCY_LEVELS

HIGH_URGENCY = "alta"


class Band(StrEnum):
    ACCEPT = "accept"
    ALERT = "alert"
    REJECT = "reject"
    UNDEFINED = "undefined"


_SEVERITY = {Band.ACCEPT: 0, Band.ALERT: 1, Band.REJECT: 2, Band.UNDEFINED: 3}


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: float
    alert: float


class SilverCriterion(BaseModel):
    """Thresholds fixed before any measurement. Change only with a new decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic_kappa: Thresholds = Thresholds(accept=0.60, alert=0.50)
    urgency_weighted_kappa: Thresholds = Thresholds(accept=0.50, alert=0.40)
    urgency_weights: KappaWeights = "linear"
    high_urgency_recall_alert: float = 0.80
    bootstrap_resamples: int = Field(default=1_000, gt=0)
    seed: int = 20261104


def band_for(value: float | None, thresholds: Thresholds) -> Band:
    if value is None:
        return Band.UNDEFINED
    if value >= thresholds.accept:
        return Band.ACCEPT
    if value >= thresholds.alert:
        return Band.ALERT
    return Band.REJECT


def worst(*bands: Band) -> Band:
    return max(bands, key=lambda band: _SEVERITY[band])


def _interval_dict(interval: Interval) -> dict[str, Any]:
    return {
        "value": interval.point,
        "ci_low": interval.low,
        "ci_high": interval.high,
        "confidence": interval.confidence,
        "resamples": interval.resamples,
        "undefined_resamples": interval.undefined_resamples,
    }


def evaluate_silver_agreement(
    gold_topic: Sequence[str],
    llm_topic: Sequence[str],
    gold_urgency: Sequence[str],
    llm_urgency: Sequence[str],
    criterion: SilverCriterion,
) -> dict[str, Any]:
    """Apply the criterion and return every number behind the decision."""
    if not len(gold_topic) == len(llm_topic) == len(gold_urgency) == len(llm_urgency):
        msg = "gold and LLM label sequences must be paired"
        raise ValueError(msg)
    resamples, seed = criterion.bootstrap_resamples, criterion.seed

    def urgency_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
        return weighted_kappa(first, second, URGENCY_LEVELS, criterion.urgency_weights)

    def high_recall(truth: Sequence[str], pred: Sequence[str]) -> float | None:
        return recall_of(truth, pred, HIGH_URGENCY)

    topic = bootstrap_interval(cohen_kappa, gold_topic, llm_topic, resamples=resamples, seed=seed)
    urgency = bootstrap_interval(
        urgency_kappa, gold_urgency, llm_urgency, resamples=resamples, seed=seed
    )
    recall = bootstrap_interval(
        high_recall, gold_urgency, llm_urgency, resamples=resamples, seed=seed
    )
    topic_band = band_for(topic.point, criterion.topic_kappa)
    urgency_band = band_for(urgency.point, criterion.urgency_weighted_kappa)
    high_support = sum(label == HIGH_URGENCY for label in gold_urgency)
    recall_alert = recall.point is not None and recall.point < criterion.high_urgency_recall_alert

    return {
        "n": len(gold_topic),
        "topic_kappa": {**_interval_dict(topic), "band": topic_band.value},
        "urgency_weighted_kappa": {
            **_interval_dict(urgency),
            "weights": criterion.urgency_weights,
            "band": urgency_band.value,
        },
        "high_urgency_recall": {
            **_interval_dict(recall),
            "support": high_support,
            "alert": recall_alert,
        },
        "support": {
            "topic": dict(sorted(Counter(gold_topic).items())),
            "urgency": {level: gold_urgency.count(level) for level in URGENCY_LEVELS},
        },
        "band": worst(topic_band, urgency_band).value,
    }


def human_ceiling_notes(
    result: dict[str, Any],
    human_topic_kappa: float | None,
    human_urgency_weighted_kappa: float | None,
    criterion: SilverCriterion,
) -> list[str]:
    """Warn when the annotator's own agreement is below what the criterion demands.

    The silver should not be required to agree with the gold more than the
    annotator agrees with themself (re-annotation after 7 days).
    """
    notes = []
    checks = (
        ("topic", "topic_kappa", human_topic_kappa, criterion.topic_kappa.accept),
        (
            "urgency",
            "urgency_weighted_kappa",
            human_urgency_weighted_kappa,
            criterion.urgency_weighted_kappa.accept,
        ),
    )
    for name, key, human, accept in checks:
        if human is not None and human < accept:
            notes.append(
                f"human re-annotation {name} kappa ({human:.2f}) is below the {key} accept "
                f"threshold ({accept:.2f}); review the criterion before deciding "
                "(docs/decisions.md)"
            )
    if result["high_urgency_recall"]["support"] == 0:
        notes.append("gold_dev has no high-urgency cases; high-urgency recall is undefined")
    return notes
