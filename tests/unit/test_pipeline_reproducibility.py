"""Same input, config and code produce the same outputs (M1 acceptance criterion)."""

import json
from pathlib import Path

import pytest

from customer_feedback_ai.data.config import DataConfig
from customer_feedback_ai.data.manifest import read_manifest, sha256_file

from .conftest import SYNTHETIC_SPLITS_CONFIG, PipelineRun, run_m1_pipeline

STAGES = ("bronze", "silver", "dev_sample", "splits", "taxonomy_review_sample")


@pytest.fixture(scope="module")
def second_run(tmp_path_factory: pytest.TempPathFactory, data_config: DataConfig) -> PipelineRun:
    return run_m1_pipeline(
        tmp_path_factory.mktemp("m1_again") / "data", data_config, SYNTHETIC_SPLITS_CONFIG
    )


def stable_view(path: Path) -> dict[str, object]:
    """Manifest without the fields that legitimately change between runs."""
    return read_manifest(path).model_dump(mode="json", exclude={"created_at", "git"})


@pytest.mark.parametrize("stage", STAGES)
def test_manifests_match_between_runs(
    m1_run: PipelineRun, second_run: PipelineRun, stage: str
) -> None:
    first = stable_view(m1_run.paths.manifest(stage))
    second = stable_view(second_run.paths.manifest(stage))
    assert first == second


@pytest.mark.parametrize("name", ["bronze_profile.json", "silver_profile.json"])
def test_profiles_match_between_runs(
    m1_run: PipelineRun, second_run: PipelineRun, name: str
) -> None:
    first = json.loads((m1_run.paths.eda_dir / name).read_text(encoding="utf-8"))
    second = json.loads((second_run.paths.eda_dir / name).read_text(encoding="utf-8"))
    assert first == second


@pytest.mark.parametrize("stage", STAGES)
def test_manifest_hashes_describe_the_files_on_disk(m1_run: PipelineRun, stage: str) -> None:
    manifest = read_manifest(m1_run.paths.manifest(stage))
    assert manifest.outputs
    for record in [*manifest.inputs, *manifest.outputs]:
        path = m1_run.paths.root / record.path
        assert sha256_file(path) == record.sha256
        assert path.stat().st_size == record.bytes


def test_manifest_records_seed_and_config(m1_run: PipelineRun) -> None:
    manifest = read_manifest(m1_run.paths.manifest("dev_sample"))
    assert manifest.seed is not None
    assert manifest.config["seed"] == manifest.seed
    assert len(manifest.config_sha256) == 64
    assert manifest.duckdb_version
