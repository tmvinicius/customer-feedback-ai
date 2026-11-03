"""Classification and agreement metrics, checked against hand-computed values."""

import pytest

from customer_feedback_ai.evaluation.metrics import (
    accuracy,
    cohen_kappa,
    macro_f1,
    per_class_scores,
    recall_of,
    weighted_kappa,
)

ORDER = ("baixa", "media", "alta")


def test_per_class_scores() -> None:
    y_true = ["a", "a", "b", "b", "c"]
    y_pred = ["a", "b", "b", "b", "a"]
    scores = {s.label: s for s in per_class_scores(y_true, y_pred)}

    assert (scores["a"].precision, scores["a"].recall, scores["a"].f1) == (0.5, 0.5, 0.5)
    assert scores["b"].precision == pytest.approx(2 / 3)
    assert scores["b"].recall == 1.0
    assert scores["b"].f1 == pytest.approx(0.8)
    assert (scores["c"].f1, scores["c"].support) == (0.0, 1)


def test_macro_f1_averages_labels_from_both_sequences() -> None:
    y_true = ["a", "a", "b", "b", "c"]
    y_pred = ["a", "b", "b", "b", "a"]
    assert macro_f1(y_true, y_pred) == pytest.approx((0.5 + 0.8 + 0.0) / 3)
    # A label only predicted, never true, still counts with F1 = 0.
    assert macro_f1(["a", "a"], ["a", "x"]) == pytest.approx((2 / 3 + 0.0) / 2)


def test_macro_f1_with_explicit_labels() -> None:
    assert macro_f1(["a"], ["a"], labels=["a", "b"]) == pytest.approx(0.5)
    assert macro_f1([], []) is None


def test_accuracy_and_recall() -> None:
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == pytest.approx(2 / 3)
    assert recall_of(["alta", "alta", "baixa"], ["alta", "media", "alta"], "alta") == 0.5
    assert recall_of(["baixa"], ["alta"], "alta") is None


def test_weighted_kappa_matches_hand_computation() -> None:
    first = ["baixa", "baixa", "media", "alta"]
    second = ["baixa", "media", "media", "alta"]
    assert weighted_kappa(first, second, ORDER, "linear") == pytest.approx(5 / 7)
    assert weighted_kappa(first, second, ORDER, "quadratic") == pytest.approx(0.8)


def test_weighted_kappa_penalizes_far_disagreements_more() -> None:
    truth = ["baixa", "media", "alta"] * 10
    near = ["media", "media", "alta"] * 10
    far = ["alta", "media", "alta"] * 10
    near_kappa = weighted_kappa(truth, near, ORDER)
    far_kappa = weighted_kappa(truth, far, ORDER)
    assert near_kappa is not None
    assert far_kappa is not None
    assert near_kappa > far_kappa
    assert cohen_kappa(truth, near) == pytest.approx(cohen_kappa(truth, far))


def test_weighted_kappa_equals_cohen_kappa_with_two_levels() -> None:
    first = ["a"] * 25 + ["b"] * 25
    second = ["a"] * 20 + ["b"] * 5 + ["a"] * 10 + ["b"] * 15
    assert weighted_kappa(first, second, ("a", "b")) == pytest.approx(cohen_kappa(first, second))


def test_weighted_kappa_edge_cases() -> None:
    assert weighted_kappa([], [], ORDER) is None
    assert weighted_kappa(["media"] * 3, ["media"] * 3, ORDER) is None
    with pytest.raises(ValueError, match="ordinal scale"):
        weighted_kappa(["urgente"], ["alta"], ORDER)
    with pytest.raises(ValueError, match="same length"):
        weighted_kappa(["alta"], [], ORDER)
