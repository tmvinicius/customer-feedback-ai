"""Silver agreement criterion (M2 acceptance) and the C4/C5 triage rules."""

import pytest

from customer_feedback_ai.evaluation.criteria import (
    Band,
    SilverCriterion,
    Thresholds,
    band_for,
    evaluate_silver_agreement,
    human_ceiling_notes,
    worst,
)
from customer_feedback_ai.evaluation.triage import Candidate, choose_larger, choose_smaller
from customer_feedback_ai.labeling.config import load_labeling_config

from .conftest import REPO_ROOT
from .test_bootstrap import TRUTH, noisy

CRITERION = SilverCriterion(bootstrap_resamples=200)
TOPICS = [f"tema_{i % 6}" for i in range(120)]
URGENCY = [("baixa", "media", "alta")[i % 3] for i in range(120)]


# --- bands -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0.60, Band.ACCEPT),
        (0.75, Band.ACCEPT),
        (0.5999, Band.ALERT),
        (0.50, Band.ALERT),
        (0.4999, Band.REJECT),
        (None, Band.UNDEFINED),
    ],
)
def test_topic_bands_follow_the_decision(value: float | None, band: Band) -> None:
    assert band_for(value, Thresholds(accept=0.60, alert=0.50)) is band


def test_worst_band_wins() -> None:
    assert worst(Band.ACCEPT, Band.ALERT) is Band.ALERT
    assert worst(Band.ALERT, Band.REJECT) is Band.REJECT
    assert worst(Band.REJECT, Band.UNDEFINED) is Band.UNDEFINED


def test_config_holds_the_decided_thresholds() -> None:
    criterion = load_labeling_config(REPO_ROOT / "configs" / "labeling.yaml").silver_criterion
    assert criterion == SilverCriterion()
    assert (criterion.topic_kappa.accept, criterion.topic_kappa.alert) == (0.60, 0.50)
    assert (criterion.urgency_weighted_kappa.accept, criterion.urgency_weighted_kappa.alert) == (
        0.50,
        0.40,
    )
    assert criterion.urgency_weights == "linear"
    assert criterion.high_urgency_recall_alert == 0.80
    assert criterion.bootstrap_resamples == 1_000


# --- evaluation ------------------------------------------------------------------


def test_perfect_agreement_is_accepted() -> None:
    result = evaluate_silver_agreement(TOPICS, TOPICS, URGENCY, URGENCY, CRITERION)
    assert result["band"] == "accept"
    assert result["topic_kappa"]["value"] == pytest.approx(1.0)
    assert result["high_urgency_recall"]["value"] == 1.0
    assert result["high_urgency_recall"]["support"] == 40
    assert result["support"]["urgency"] == {"baixa": 40, "media": 40, "alta": 40}


def test_the_worse_of_topic_and_urgency_decides() -> None:
    reversed_urgency = [{"baixa": "alta", "alta": "baixa"}.get(u, u) for u in URGENCY]
    result = evaluate_silver_agreement(TOPICS, TOPICS, URGENCY, reversed_urgency, CRITERION)

    assert result["topic_kappa"]["band"] == "accept"
    assert result["urgency_weighted_kappa"]["band"] == "reject"
    assert result["band"] == "reject"


def test_missing_high_urgency_only_alerts() -> None:
    no_high = ["media" if u == "alta" else u for u in URGENCY]
    result = evaluate_silver_agreement(TOPICS, TOPICS, URGENCY, no_high, CRITERION)
    assert result["high_urgency_recall"]["value"] == 0.0
    assert result["high_urgency_recall"]["alert"] is True
    assert result["band"] in {"accept", "alert", "reject"}  # decided by the kappas only


def flip(labels: list[str], every: int) -> list[str]:
    """Replace every n-th label with the next label of the same set."""
    choices = sorted(set(labels))
    return [
        choices[(choices.index(x) + 1) % len(choices)] if i % every == 0 else x
        for i, x in enumerate(labels)
    ]


def test_intervals_are_reported_with_the_point() -> None:
    result = evaluate_silver_agreement(
        TOPICS, flip(TOPICS, 4), URGENCY, flip(URGENCY, 5), CRITERION
    )
    topic = result["topic_kappa"]
    assert topic["ci_low"] <= topic["value"] <= topic["ci_high"]
    assert topic["resamples"] == 200


def test_human_ceiling_is_flagged() -> None:
    result = evaluate_silver_agreement(TOPICS, TOPICS, URGENCY, URGENCY, CRITERION)
    notes = human_ceiling_notes(result, 0.55, 0.70, CRITERION)
    assert len(notes) == 1
    assert "topic kappa (0.55)" in notes[0]
    assert human_ceiling_notes(result, None, None, CRITERION) == []


def test_sequences_must_be_paired() -> None:
    with pytest.raises(ValueError, match="paired"):
        evaluate_silver_agreement(["a"], [], ["alta"], ["alta"], CRITERION)


# --- triage ----------------------------------------------------------------------


def test_c4_clear_winner_by_macro_f1() -> None:
    good = Candidate("gemma-4-e4b", tuple(noisy(TRUTH, 0.1, seed=1)), latency_p50_s=2.0)
    bad = Candidate("qwen-3.5-4b", tuple(noisy(TRUTH, 0.7, seed=2)), latency_p50_s=0.5)
    decision = choose_smaller(TRUTH, good, bad, resamples=300)

    assert decision.winner == "gemma-4-e4b"
    assert "higher topic macro-F1" in decision.reason
    assert decision.difference is not None
    assert not decision.difference.contains(0.0)


def test_c4_tie_goes_to_the_faster_model() -> None:
    same = tuple(noisy(TRUTH, 0.3, seed=3))
    slow = Candidate("gemma-4-e4b", same, latency_p50_s=2.0)
    fast = Candidate("qwen-3.5-4b", same, latency_p50_s=0.8)
    decision = choose_smaller(TRUTH, slow, fast, resamples=300)

    assert decision.winner == "qwen-3.5-4b"
    assert decision.reason.startswith("tie")


def test_c5_drops_candidates_that_are_not_viable() -> None:
    best = Candidate("qwen-3.5-9b", tuple(TRUTH), latency_p50_s=3.0, viable=False)
    fits = Candidate("llama-3.1-8b", tuple(noisy(TRUTH, 0.4, seed=4)), latency_p50_s=2.5)
    decision = choose_larger(TRUTH, [best, fits])

    assert decision.winner == "llama-3.1-8b"
    assert "qwen-3.5-9b" in decision.reason


def test_c5_is_cut_when_nothing_is_viable() -> None:
    candidates = [
        Candidate("qwen-3.5-9b", tuple(TRUTH), 3.0, viable=False),
        Candidate("llama-3.1-8b", tuple(TRUTH), 2.5, viable=False),
    ]
    decision = choose_larger(TRUTH, candidates)
    assert decision.winner is None
    assert "cut" in decision.reason


def test_c5_takes_the_higher_macro_f1_when_both_are_viable() -> None:
    better = Candidate("qwen-3.5-9b", tuple(noisy(TRUTH, 0.1, seed=5)), 3.0)
    worse = Candidate("llama-3.1-8b", tuple(noisy(TRUTH, 0.5, seed=6)), 2.0)
    assert choose_larger(TRUTH, [worse, better]).winner == "qwen-3.5-9b"


def test_c5_exact_tie_says_so_and_goes_to_the_faster_model() -> None:
    slow = Candidate("qwen-3.5-9b", tuple(TRUTH), 3.0)
    fast = Candidate("llama-3.1-8b", tuple(TRUTH), 2.0)
    decision = choose_larger(TRUTH, [slow, fast])
    assert decision.winner == "llama-3.1-8b"
    assert decision.reason.startswith("exact tie")
