"""Versioned data configs load and match the plan in AGENTS.md."""

from datetime import date

from customer_feedback_ai.data.config import load_data_config, load_splits_config

from .conftest import REPO_ROOT

CONFIGS = REPO_ROOT / "configs"


def test_splits_config_matches_the_plan() -> None:
    config = load_splits_config(CONFIGS / "splits.yaml")
    windows = config.windows

    assert windows.train.start is None
    assert windows.train.end == date(2023, 12, 31)
    assert (windows.val.start, windows.val.end) == (date(2024, 1, 1), date(2024, 6, 30))
    assert windows.test.start == date(2024, 7, 1)
    assert windows.test.end is None
    assert config.holdout_companies.fraction == 0.05


def test_data_config_loads() -> None:
    config = load_data_config(CONFIGS / "data.yaml")
    assert config.sample.dev_sample_size == 50_000
    assert config.sample.taxonomy_review_size == 200
    assert config.paper_reference is not None
    assert config.paper_reference.records == 3_150_552
