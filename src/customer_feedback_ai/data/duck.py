"""DuckDB connection with the project's settings."""

from pathlib import Path

import duckdb

from customer_feedback_ai.data.config import DuckDBConfig
from customer_feedback_ai.data.sql import literal


def connect(tmp_dir: Path, config: DuckDBConfig | None = None) -> duckdb.DuckDBPyConnection:
    """In-memory connection that spills to `tmp_dir` and keeps insertion order."""
    config = config or DuckDBConfig()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory = {literal(tmp_dir)}")
    con.execute("SET preserve_insertion_order = true")
    if config.memory_limit is not None:
        con.execute(f"SET memory_limit = {literal(config.memory_limit)}")
    return con


def count_rows(con: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    row = con.execute(f"SELECT count(*) FROM read_parquet({literal(parquet)})").fetchone()
    assert row is not None
    return int(row[0])
