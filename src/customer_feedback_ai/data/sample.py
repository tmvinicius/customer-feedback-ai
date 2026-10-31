"""Deterministic samples: `dev_sample` for fast iteration and the taxonomy review sample.

Rows are ranked by the hash of a seed and the text hash, so the same input and
seed always produce the same sample, regardless of row order or thread count.
"""

from pathlib import Path

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.schema import TEXT_COLUMN, TEXT_HASH_COLUMN


def _rank(seed: int, purpose: str) -> str:
    return f"sha256({sql.literal(f'{seed}:{purpose}:')} || {TEXT_HASH_COLUMN})"


def write_dev_sample(
    con: duckdb.DuckDBPyConnection, silver: Path, output: Path, size: int, seed: int
) -> int:
    """Uniform sample of silver rows, written in the same order as silver."""
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT * FROM (
                SELECT * FROM read_parquet({sql.literal(silver)})
                ORDER BY {_rank(seed, "dev_sample")} LIMIT {int(size)}
            )
            ORDER BY data_abertura NULLS LAST, {TEXT_HASH_COLUMN}
        ) TO {sql.literal(output)} (FORMAT parquet, COMPRESSION zstd)
        """
    )
    row = con.execute(f"SELECT count(*) FROM read_parquet({sql.literal(output)})").fetchone()
    assert row is not None
    return int(row[0])


def write_taxonomy_review_sample(
    con: duckdb.DuckDBPyConnection, train: Path, output: Path, size: int, seed: int
) -> int:
    """Complaints from `train` for the maintainer to read before G2.

    Only the identifier and the complaint text are exported. The sample comes from
    the train window, so reading it does not expose evaluation data.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT {sql.ident("ID")}, {sql.ident(TEXT_COLUMN)}
            FROM read_parquet({sql.literal(train)})
            ORDER BY {_rank(seed, "taxonomy_review")} LIMIT {int(size)}
        ) TO {sql.literal(output)} (FORMAT csv, HEADER true)
        """
    )
    row = con.execute(
        f"SELECT count(*) FROM read_csv({sql.literal(output)}, header = true)"
    ).fetchone()
    assert row is not None
    return int(row[0])
