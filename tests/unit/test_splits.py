"""Splits are temporal, never overlap and keep hidden companies out of train and val."""

import hashlib
from datetime import date
from itertools import combinations
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from customer_feedback_ai.data.clean import build_silver
from customer_feedback_ai.data.config import DataConfig, SplitWindows, Window
from customer_feedback_ai.data.ingest import write_bronze
from customer_feedback_ai.data.splits import (
    SPLITS,
    TEST,
    TEST_UNSEEN_COMPANY,
    TRAIN,
    VAL,
    SplitIntegrityError,
    build_splits,
    is_hidden_company,
    verify_splits,
)
from customer_feedback_ai.data.sql import literal

from .conftest import EDGE_CASES_CSV, SYNTHETIC_SPLITS_CONFIG, PipelineRun, make_splits_config


def values(con: duckdb.DuckDBPyConnection, path: Path, column: str) -> set[object]:
    query = (
        f"SELECT DISTINCT {column} FROM read_parquet({literal(path)}) WHERE {column} IS NOT NULL"
    )
    return {row[0] for row in con.execute(query).fetchall()}


def test_no_row_or_text_is_shared_between_splits(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    paths = m1_run.splits.paths
    for left, right in combinations(SPLITS, 2):
        for column in ("ID", "text_hash"):
            shared = values(con, paths[left], column) & values(con, paths[right], column)
            assert not shared, f"{left} and {right} share {column}"


def test_every_split_respects_its_date_window(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    windows = SYNTHETIC_SPLITS_CONFIG.windows
    expected = {TRAIN: windows.train, VAL: windows.val, TEST: windows.test}
    expected[TEST_UNSEEN_COMPANY] = windows.test
    for split, window in expected.items():
        raw = values(con, m1_run.splits.paths[split], "CAST(data_abertura AS DATE)")
        dates = {value for value in raw if isinstance(value, date)}
        assert dates, f"{split} is empty"
        assert window.start is None or min(dates) >= window.start
        assert window.end is None or max(dates) <= window.end


def test_hidden_companies_only_appear_in_test_unseen_company(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    paths = m1_run.splits.paths
    unseen = values(con, paths[TEST_UNSEEN_COMPANY], "company_key")
    salt = SYNTHETIC_SPLITS_CONFIG.holdout_companies.salt
    fraction = SYNTHETIC_SPLITS_CONFIG.holdout_companies.fraction

    assert unseen, "the synthetic run should hide at least one company"
    assert all(is_hidden_company(str(key), salt, fraction) for key in unseen)
    for split in (TRAIN, VAL, TEST):
        assert not values(con, paths[split], "company_key") & unseen


def test_every_dated_row_is_assigned_or_counted(m1_run: PipelineRun) -> None:
    con = duckdb.connect()
    silver = m1_run.paths.silver
    row = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE data_abertura IS NULL) "
        f"FROM read_parquet({literal(silver)})"
    ).fetchone()
    assert row is not None
    total, missing_date = row
    result = m1_run.splits

    assert result.excluded_missing_date == missing_date > 0
    assert result.excluded_hidden_company_before_test > 0
    assert (
        sum(result.rows.values())
        + result.excluded_missing_date
        + result.excluded_hidden_company_before_test
        + result.excluded_outside_windows
        == total
    )


def test_window_boundaries(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, data_config: DataConfig
) -> None:
    bronze, silver = tmp_path / "bronze.parquet", tmp_path / "silver.parquet"
    write_bronze(con, EDGE_CASES_CSV, bronze, data_config.csv)
    build_silver(con, bronze, silver)
    no_hidden = make_splits_config(1e-12)

    result = build_splits(con, silver, tmp_path / "splits", no_hidden)
    ids = {split: values(con, path, '"ID"') for split, path in result.paths.items()}

    assert {"E-01", "E-08"} <= ids[TRAIN]  # 2022-03-15 and 2023-12-31
    assert {"E-05", "E-09", "E-10"} <= ids[VAL]  # 2024-02-10, 2024-01-01, 2024-06-30 23:59
    assert {"E-06", "E-11", "E-12"} <= ids[TEST]  # 2024-08-01, 2024-07-01, 2025-04-30
    assert ids[TEST_UNSEEN_COMPANY] == set()
    assert result.excluded_missing_date == 1  # E-07


def test_hidden_company_decision_does_not_depend_on_other_companies() -> None:
    names = [f"empresa {i}" for i in range(4_000)]
    alone = [is_hidden_company(name, "salt", 0.05) for name in names]
    assert alone == [is_hidden_company(name, "salt", 0.05) for name in reversed(names)][::-1]
    assert 0.04 < sum(alone) / len(names) < 0.06


def test_hidden_company_hash_is_stable() -> None:
    digest = hashlib.sha256(b"salt:empresa 1").digest()
    expected = int.from_bytes(digest[:8], "big") / 2**64 < 0.05
    assert is_hidden_company("empresa 1", "salt", 0.05) is expected


def test_verification_catches_overlapping_splits(
    m1_run: PipelineRun, con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    paths = dict(m1_run.splits.paths)
    leaked = tmp_path / "test_with_leak.parquet"
    con.execute(
        f"COPY (SELECT * FROM read_parquet({literal(paths[TEST])}) UNION ALL "
        f"(SELECT * FROM read_parquet({literal(paths[TRAIN])}) LIMIT 1)) TO {literal(leaked)}"
    )
    paths[TEST] = leaked
    con.execute("CREATE TEMP TABLE hidden_companies (company_key VARCHAR)")

    with pytest.raises(SplitIntegrityError, match="train__test share"):
        verify_splits(con, paths, SYNTHETIC_SPLITS_CONFIG)


@pytest.mark.parametrize(
    "windows",
    [
        {"train_end": date(2024, 1, 1), "val_start": date(2024, 1, 1)},  # overlap
        {"val_end": date(2024, 7, 1), "test_start": date(2024, 7, 1)},  # overlap
        {"val_start": date(2024, 7, 1), "val_end": date(2024, 1, 1)},  # reversed
    ],
)
def test_overlapping_or_reversed_windows_are_rejected(windows: dict[str, date]) -> None:
    bounds = {
        "train_end": date(2023, 12, 31),
        "val_start": date(2024, 1, 1),
        "val_end": date(2024, 6, 30),
        "test_start": date(2024, 7, 1),
    } | windows
    with pytest.raises(ValidationError):
        SplitWindows(
            train=Window(end=bounds["train_end"]),
            val=Window(start=bounds["val_start"], end=bounds["val_end"]),
            test=Window(start=bounds["test_start"]),
        )
