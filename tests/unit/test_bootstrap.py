"""Bootstrap intervals: deterministic, paired and honest about undefined resamples."""

import random

import pytest

from customer_feedback_ai.evaluation.bootstrap import (
    bootstrap_interval,
    paired_bootstrap_difference,
    quantile,
)
from customer_feedback_ai.evaluation.metrics import accuracy, cohen_kappa, macro_f1

LABELS = ["a", "b", "c", "d"]


def noisy(truth: list[str], error_rate: float, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [rng.choice(LABELS) if rng.random() < error_rate else t for t in truth]


TRUTH = [LABELS[i % 4] for i in range(150)]


def test_quantile_interpolates() -> None:
    assert quantile([0.0, 1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert quantile([0.0, 10.0], 0.25) == pytest.approx(2.5)
    with pytest.raises(ValueError, match="empty"):
        quantile([], 0.5)


def test_interval_is_deterministic_and_brackets_the_point() -> None:
    pred = noisy(TRUTH, 0.3, seed=1)
    first = bootstrap_interval(macro_f1, TRUTH, pred, seed=7)
    second = bootstrap_interval(macro_f1, TRUTH, pred, seed=7)
    other_seed = bootstrap_interval(macro_f1, TRUTH, pred, seed=8)

    assert first == second
    assert first != other_seed
    assert first.point == pytest.approx(macro_f1(TRUTH, pred))
    assert first.low is not None
    assert first.high is not None
    assert first.point is not None
    assert first.low < first.point < first.high
    assert first.resamples == 1_000
    assert first.confidence == 0.95


def test_perfect_predictions_have_a_degenerate_interval() -> None:
    interval = bootstrap_interval(accuracy, TRUTH, TRUTH, resamples=200)
    assert (interval.point, interval.low, interval.high) == (1.0, 1.0, 1.0)


def test_undefined_resamples_are_counted() -> None:
    truth = ["a"] * 49 + ["b"]
    interval = bootstrap_interval(cohen_kappa, truth, truth, resamples=500, seed=3)
    # Resamples that miss the single "b" have one category only: kappa is undefined.
    assert 0 < interval.undefined_resamples < 500


def test_paired_difference_of_identical_models_is_zero() -> None:
    pred = noisy(TRUTH, 0.3, seed=2)
    interval = paired_bootstrap_difference(macro_f1, TRUTH, pred, pred, resamples=200)
    assert (interval.point, interval.low, interval.high) == (0.0, 0.0, 0.0)
    assert interval.contains(0.0)


def test_paired_difference_detects_a_clearly_better_model() -> None:
    good, bad = noisy(TRUTH, 0.1, seed=3), noisy(TRUTH, 0.7, seed=4)
    interval = paired_bootstrap_difference(macro_f1, TRUTH, good, bad, seed=5)
    assert interval.low is not None
    assert interval.low > 0
    assert not interval.contains(0.0)


def test_sequences_must_be_paired() -> None:
    with pytest.raises(ValueError, match="same length"):
        bootstrap_interval(accuracy, ["a"], [])
    with pytest.raises(ValueError, match="same length"):
        paired_bootstrap_difference(accuracy, ["a"], ["a"], [])
