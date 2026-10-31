"""Bronze to silver: cleaning and deduplication keep the oldest occurrence."""

from pathlib import Path

import duckdb
import pytest

from customer_feedback_ai.data.clean import SilverResult, build_silver
from customer_feedback_ai.data.config import DataConfig
from customer_feedback_ai.data.ingest import write_bronze
from customer_feedback_ai.data.sql import literal

from .conftest import EDGE_CASES_CSV


@pytest.fixture
def silver(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, data_config: DataConfig
) -> tuple[SilverResult, dict[str, dict[str, object]]]:
    bronze = tmp_path / "bronze.parquet"
    output = tmp_path / "silver.parquet"
    write_bronze(con, EDGE_CASES_CSV, bronze, data_config.csv)
    result = build_silver(con, bronze, output)
    cursor = con.execute(f"SELECT * FROM read_parquet({literal(output)})")
    names = [d[0] for d in cursor.description]
    rows = {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}
    return result, rows


def test_counts_add_up(silver: tuple[SilverResult, dict[str, dict[str, object]]]) -> None:
    result, rows = silver
    assert result.rows_in == 12
    assert result.dropped_empty_text == 1
    assert result.dropped_duplicates == 2
    assert result.duplicate_groups == 1
    assert result.rows_out == len(rows) == 9


def test_oldest_dated_occurrence_is_kept(
    silver: tuple[SilverResult, dict[str, dict[str, object]]],
) -> None:
    _, rows = silver
    # E-01 (2022-03-15), E-02 (2022-04-01, upper case) and E-03 (no date) are the same text.
    assert "E-01" in rows
    assert "E-02" not in rows
    assert "E-03" not in rows


def test_blank_complaints_are_dropped(
    silver: tuple[SilverResult, dict[str, dict[str, object]]],
) -> None:
    _, rows = silver
    assert "E-04" not in rows


def test_text_is_cleaned_without_losing_tags(
    silver: tuple[SilverResult, dict[str, dict[str, object]]],
) -> None:
    _, rows = silver
    assert rows["E-05"]["reclamacao_labeled"] == (
        "Meu nome é [NOME] e meu e-mail [EMAIL] foi usado numa compra que não fiz."
    )
    assert rows["E-06"]["empresa"] == "Loja Exemplo ÁCME"
    assert rows["E-06"]["company_key"] == rows["E-01"]["company_key"] == "loja exemplo acme"


def test_hashes_are_present_and_unique(
    silver: tuple[SilverResult, dict[str, dict[str, object]]],
) -> None:
    _, rows = silver
    hashes = [row["text_hash"] for row in rows.values()]
    assert all(isinstance(value, str) and len(value) == 64 for value in hashes)
    assert len(set(hashes)) == len(hashes)
