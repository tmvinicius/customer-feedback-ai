"""dev_sample and the taxonomy review sample are deterministic and come from the right data."""

import csv
from pathlib import Path

import duckdb

from customer_feedback_ai.data.sample import write_dev_sample
from customer_feedback_ai.data.sql import literal

from .conftest import PipelineRun


def column(con: duckdb.DuckDBPyConnection, path: Path, name: str) -> list[object]:
    return [
        row[0]
        for row in con.execute(f"SELECT {name} FROM read_parquet({literal(path)})").fetchall()
    ]


def test_dev_sample_is_a_subset_of_silver(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    sample = column(con, m1_run.paths.dev_sample, "text_hash")
    silver = set(column(con, m1_run.paths.silver, "text_hash"))
    assert len(sample) == 1_000
    assert set(sample) <= silver


def test_dev_sample_depends_only_on_seed(m1_run: PipelineRun, tmp_path: Path) -> None:
    con = duckdb.connect()
    silver = m1_run.paths.silver
    same = tmp_path / "same.parquet"
    other = tmp_path / "other.parquet"
    write_dev_sample(con, silver, same, size=1_000, seed=20260101)
    write_dev_sample(con, silver, other, size=1_000, seed=1)

    original = column(con, m1_run.paths.dev_sample, "text_hash")
    assert column(con, same, "text_hash") == original
    assert column(con, other, "text_hash") != original


def test_taxonomy_sample_comes_from_train_with_text_only(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    with m1_run.paths.taxonomy_review_sample.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    train_ids = set(column(con, m1_run.splits.paths["train"], '"ID"'))

    assert len(rows) == 50
    assert set(rows[0]) == {"ID", "reclamacao_labeled"}
    assert {row["ID"] for row in rows} <= train_ids
