"""Shared fixtures for the data pipeline tests. All data here is synthetic."""

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pytest

from customer_feedback_ai.data.config import (
    DataConfig,
    HoldoutConfig,
    SplitsConfig,
    SplitWindows,
    Window,
    load_data_config,
)
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.splits import SplitResult
from customer_feedback_ai.data.synthetic import write_synthetic_csv
from customer_feedback_ai.labeling.config import GoldConfig, LabelingConfig, SilverConfig
from customer_feedback_ai.pipelines import data as data_pipeline
from customer_feedback_ai.pipelines import gold_sample as gold_sample_pipeline
from customer_feedback_ai.pipelines import sample as sample_pipeline
from customer_feedback_ai.pipelines import splits as splits_pipeline
from customer_feedback_ai.pipelines import taxonomy_sample as taxonomy_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
EDGE_CASES_CSV = FIXTURES / "consumerbr_edge_cases.csv"

SYNTHETIC_ROWS = 3_000
SYNTHETIC_SEED = 11


def make_splits_config(fraction: float) -> SplitsConfig:
    """Windows from AGENTS.md with a configurable share of hidden companies."""
    return SplitsConfig(
        windows=SplitWindows(
            train=Window(end=date(2023, 12, 31)),
            val=Window(start=date(2024, 1, 1), end=date(2024, 6, 30)),
            test=Window(start=date(2024, 7, 1)),
        ),
        holdout_companies=HoldoutConfig(fraction=fraction, salt="tests"),
    )


# With 20 synthetic companies, 0.3 hides a handful, so the hidden-company rules are exercised.
SYNTHETIC_SPLITS_CONFIG = make_splits_config(0.3)


@pytest.fixture(scope="session")
def data_config() -> DataConfig:
    config = load_data_config(REPO_ROOT / "configs" / "data.yaml")
    sample = config.sample.model_copy(update={"dev_sample_size": 1_000, "taxonomy_review_size": 50})
    return config.model_copy(update={"sample": sample})


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect(tmp_path / "duckdb_tmp")
    yield connection
    connection.close()


@dataclass(frozen=True)
class PipelineRun:
    paths: DataPaths
    splits: SplitResult


def run_m1_pipeline(root: Path, config: DataConfig, splits_config: SplitsConfig) -> PipelineRun:
    """Synthetic CSV -> bronze -> silver -> dev_sample -> splits -> taxonomy sample."""
    paths = DataPaths(root)
    write_synthetic_csv(paths.raw_dir / "synthetic.csv", SYNTHETIC_ROWS, SYNTHETIC_SEED)
    data_pipeline.run(paths, config)
    sample_pipeline.run(paths, config)
    result = splits_pipeline.run(paths, splits_config, duckdb_config=config.duckdb)
    taxonomy_pipeline.run(paths, config)
    return PipelineRun(paths=paths, splits=result)


@pytest.fixture(scope="session")
def m1_run(tmp_path_factory: pytest.TempPathFactory, data_config: DataConfig) -> PipelineRun:
    return run_m1_pipeline(
        tmp_path_factory.mktemp("m1") / "data", data_config, SYNTHETIC_SPLITS_CONFIG
    )


# --- M2: labeling ---------------------------------------------------------------

SMALL_LABELING = LabelingConfig(
    gold=GoldConfig(
        gold_dev_size=40,
        gold_test_size=60,
        gold_test_unseen_share=0.25,
        reannotation_fraction=0.1,
        reannotation_min_days=7,
        min_examples_per_topic_in_gold_dev=5,
        min_high_urgency_in_gold_test=30,
        seed=1,
    ),
    silver=SilverConfig(
        silver_train_size=200,
        silver_val_size=50,
        seed=2,
        model_role="cheap",
        prompt=REPO_ROOT / "prompts" / "classify" / "v1.md",
        effort="low",
        max_tokens=1024,
        batch_chunk_size=100,
        chars_per_token=3.5,
        expected_output_tokens=200,
    ),
)


@pytest.fixture
def labeling_paths(m1_run: PipelineRun, tmp_path: Path) -> DataPaths:
    """A data directory with the synthetic splits and a small annotation queue."""
    paths = DataPaths(tmp_path / "data")
    shutil.copytree(m1_run.paths.splits_dir("silver"), paths.splits_dir("silver"))
    gold_sample_pipeline.run(paths, SMALL_LABELING)
    return paths
