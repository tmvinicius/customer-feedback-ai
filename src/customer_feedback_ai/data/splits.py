"""Silver to gold: temporal splits and hidden companies (AGENTS.md, section 6).

- `train`, `val` and `test` follow the date windows in `configs/splits.yaml`.
- About 5% of companies are hidden. A company is hidden when the hash of its
  normalized name falls below the configured fraction, so the decision does not
  depend on which other companies exist. Hidden companies never appear in
  `train` or `val`. Their complaints inside the test window form
  `test_unseen_company`, and their older complaints are left out.
- Rows without `data_abertura` are left out and counted.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.config import SplitsConfig, Window
from customer_feedback_ai.data.schema import (
    COMPANY_KEY_COLUMN,
    LOOSE_HASH_COLUMN,
    SPLIT_COLUMN,
    TEXT_HASH_COLUMN,
)
from customer_feedback_ai.errors import DataPipelineError

TRAIN, VAL, TEST, TEST_UNSEEN_COMPANY = "train", "val", "test", "test_unseen_company"
SPLITS: tuple[str, ...] = (TRAIN, VAL, TEST, TEST_UNSEEN_COMPANY)
EVALUATION_SPLITS: tuple[str, ...] = (VAL, TEST, TEST_UNSEEN_COMPANY)

_HASH_SPACE = 2**64


class SplitIntegrityError(DataPipelineError):
    """The written splits violate an invariant, such as overlapping rows."""


@dataclass(frozen=True)
class SplitResult:
    paths: dict[str, Path]
    rows: dict[str, int]
    excluded_missing_date: int
    excluded_hidden_company_before_test: int
    excluded_outside_windows: int
    companies: int
    hidden_companies: int
    checks: dict[str, Any]


def hidden_company_score(company_key: str, salt: str) -> float:
    """Uniform value in [0, 1) derived from the company name."""
    digest = hashlib.sha256(f"{salt}:{company_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / _HASH_SPACE


def is_hidden_company(company_key: str, salt: str, fraction: float) -> bool:
    return hidden_company_score(company_key, salt) < fraction


def _date_condition(window: Window) -> str:
    column = "CAST(data_abertura AS DATE)"
    parts = []
    if window.start is not None:
        parts.append(f"{column} >= DATE {sql.literal(window.start.isoformat())}")
    if window.end is not None:
        parts.append(f"{column} <= DATE {sql.literal(window.end.isoformat())}")
    return " AND ".join(parts) if parts else "true"


def _register_hidden_companies(
    con: duckdb.DuckDBPyConnection, source: Path, config: SplitsConfig
) -> tuple[int, int]:
    keys = [
        str(row[0])
        for row in con.execute(
            f"SELECT DISTINCT {COMPANY_KEY_COLUMN} FROM read_parquet({sql.literal(source)}) "
            f"WHERE {COMPANY_KEY_COLUMN} IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    holdout = config.holdout_companies
    hidden = [key for key in keys if is_hidden_company(key, holdout.salt, holdout.fraction)]
    con.execute(f"CREATE OR REPLACE TEMP TABLE hidden_companies ({COMPANY_KEY_COLUMN} VARCHAR)")
    if hidden:
        con.executemany("INSERT INTO hidden_companies VALUES (?)", [(key,) for key in hidden])
    return len(keys), len(hidden)


def build_splits(
    con: duckdb.DuckDBPyConnection, source: Path, output_dir: Path, config: SplitsConfig
) -> SplitResult:
    companies, hidden = _register_hidden_companies(con, source, config)
    windows = config.windows
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW assigned AS
        WITH flagged AS (
            SELECT s.*, h.{COMPANY_KEY_COLUMN} IS NOT NULL AS is_hidden
            FROM read_parquet({sql.literal(source)}) AS s
            LEFT JOIN hidden_companies AS h USING ({COMPANY_KEY_COLUMN})
        )
        SELECT * EXCLUDE (is_hidden),
            CASE
                WHEN data_abertura IS NULL THEN NULL
                WHEN is_hidden THEN
                    CASE WHEN {_date_condition(windows.test)} THEN '{TEST_UNSEEN_COMPANY}' END
                WHEN {_date_condition(windows.train)} THEN '{TRAIN}'
                WHEN {_date_condition(windows.val)} THEN '{VAL}'
                WHEN {_date_condition(windows.test)} THEN '{TEST}'
            END AS {SPLIT_COLUMN},
            CASE
                WHEN data_abertura IS NULL THEN 'missing_date'
                WHEN is_hidden AND NOT ({_date_condition(windows.test)})
                    THEN 'hidden_company_before_test'
            END AS exclusion
        FROM flagged
        """
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for split in SPLITS:
        path = output_dir / f"{split}.parquet"
        con.execute(
            f"""
            COPY (
                SELECT * EXCLUDE (exclusion) FROM assigned WHERE {SPLIT_COLUMN} = '{split}'
                ORDER BY data_abertura, {TEXT_HASH_COLUMN}
            ) TO {sql.literal(path)} (FORMAT parquet, COMPRESSION zstd)
            """
        )
        paths[split] = path

    counts = dict(
        con.execute(
            "SELECT coalesce(split, exclusion, 'outside_windows'), count(*) "
            "FROM assigned GROUP BY 1"
        ).fetchall()
    )
    checks = verify_splits(con, paths, config)
    return SplitResult(
        paths=paths,
        rows={split: int(counts.get(split, 0)) for split in SPLITS},
        excluded_missing_date=int(counts.get("missing_date", 0)),
        excluded_hidden_company_before_test=int(counts.get("hidden_company_before_test", 0)),
        excluded_outside_windows=int(counts.get("outside_windows", 0)),
        companies=companies,
        hidden_companies=hidden,
        checks=checks,
    )


def _scalar(con: duckdb.DuckDBPyConnection, query: str) -> Any:
    row = con.execute(query).fetchone()
    assert row is not None
    return row[0]


def _overlap(con: duckdb.DuckDBPyConnection, column: str, left: Path, right: Path) -> int:
    """Number of distinct non-null values of `column` present in both files."""
    name = sql.ident(column)
    return int(
        _scalar(
            con,
            f"SELECT count(*) FROM ("
            f"SELECT DISTINCT {name} FROM read_parquet({sql.literal(left)}) "
            f"WHERE {name} IS NOT NULL "
            "INTERSECT "
            f"SELECT DISTINCT {name} FROM read_parquet({sql.literal(right)}))",
        )
    )


def _date_range(con: duckdb.DuckDBPyConnection, path: Path) -> tuple[date | None, date | None]:
    row = con.execute(
        f"SELECT min(CAST(data_abertura AS DATE)), max(CAST(data_abertura AS DATE)) "
        f"FROM read_parquet({sql.literal(path)})"
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def _within(window: Window, observed: tuple[date | None, date | None]) -> bool:
    low, high = observed
    if low is None or high is None:
        return True
    return (window.start is None or low >= window.start) and (
        window.end is None or high <= window.end
    )


def verify_splits(
    con: duckdb.DuckDBPyConnection, paths: dict[str, Path], config: SplitsConfig
) -> dict[str, Any]:
    """Check the invariants of written splits. Raises on violation, returns the evidence."""
    problems: list[str] = []
    overlaps: dict[str, dict[str, int]] = {}
    for left, right in combinations(SPLITS, 2):
        pair = f"{left}__{right}"
        overlaps[pair] = {
            column: _overlap(con, column, paths[left], paths[right])
            for column in ("ID", TEXT_HASH_COLUMN)
        }
        problems += [
            f"{pair} share {n} {column} values" for column, n in overlaps[pair].items() if n
        ]

    hidden_in_seen = sum(
        int(
            _scalar(
                con,
                f"SELECT count(*) FROM read_parquet({sql.literal(paths[split])}) "
                f"WHERE {COMPANY_KEY_COLUMN} IN "
                f"(SELECT {COMPANY_KEY_COLUMN} FROM hidden_companies)",
            )
        )
        for split in (TRAIN, VAL, TEST)
    )
    if hidden_in_seen:
        problems.append(f"{hidden_in_seen} rows of hidden companies outside {TEST_UNSEEN_COMPANY}")
    seen_in_unseen = int(
        _scalar(
            con,
            f"SELECT count(*) FROM read_parquet({sql.literal(paths[TEST_UNSEEN_COMPANY])}) "
            f"WHERE {COMPANY_KEY_COLUMN} IS NULL OR {COMPANY_KEY_COLUMN} NOT IN "
            f"(SELECT {COMPANY_KEY_COLUMN} FROM hidden_companies)",
        )
    )
    if seen_in_unseen:
        problems.append(f"{seen_in_unseen} rows of visible companies in {TEST_UNSEEN_COMPANY}")

    windows = config.windows
    expected = {TRAIN: windows.train, VAL: windows.val, TEST: windows.test}
    expected[TEST_UNSEEN_COMPANY] = windows.test
    date_ranges = {split: _date_range(con, paths[split]) for split in SPLITS}
    problems += [
        f"{split} has dates outside its window: {date_ranges[split]}"
        for split, window in expected.items()
        if not _within(window, date_ranges[split])
    ]

    if problems:
        raise SplitIntegrityError("; ".join(problems))

    near_duplicates = {
        split: _overlap(con, LOOSE_HASH_COLUMN, paths[TRAIN], paths[split])
        for split in EVALUATION_SPLITS
    }
    return {
        "overlaps": overlaps,
        "hidden_company_rows_outside_unseen": hidden_in_seen,
        "visible_company_rows_in_unseen": seen_in_unseen,
        "date_ranges": {
            split: [None if d is None else d.isoformat() for d in rng]
            for split, rng in date_ranges.items()
        },
        # Informational: loose-hash groups shared with train. Not removed.
        "near_duplicate_groups_shared_with_train": near_duplicates,
    }
