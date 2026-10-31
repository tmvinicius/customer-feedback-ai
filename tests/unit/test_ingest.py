"""Raw CSV to bronze: column checks, typing rules and failure handling."""

import csv
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from customer_feedback_ai.data.config import CsvConfig, DataConfig, ValidationConfig
from customer_feedback_ai.data.ingest import (
    CastValidationError,
    SchemaError,
    validate_csv,
    write_bronze,
)
from customer_feedback_ai.data.schema import RAW_COLUMN_NAMES
from customer_feedback_ai.data.sql import literal

from .conftest import EDGE_CASES_CSV


def bronze_rows(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, config: DataConfig
) -> dict[str, dict[str, object]]:
    output = tmp_path / "bronze.parquet"
    write_bronze(con, EDGE_CASES_CSV, output, config.csv)
    cursor = con.execute(f"SELECT * FROM read_parquet({literal(output)})")
    names = [d[0] for d in cursor.description]
    return {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def valid_row(index: int, **overrides: str) -> list[str]:
    row = {name: "" for name in RAW_COLUMN_NAMES}
    row.update(ID=f"R-{index}", id_reclamacao=str(index), reclamacao_labeled=f"Texto {index}")
    row.update(data_abertura="2024-01-01 10:00:00", padronizada="true", avaliacao_nota="4")
    row.update(overrides)
    return [row[name] for name in RAW_COLUMN_NAMES]


def test_edge_cases_validate_without_failures(
    con: duckdb.DuckDBPyConnection, data_config: DataConfig
) -> None:
    result = validate_csv(con, EDGE_CASES_CSV, data_config.csv, data_config.validation)

    assert result.rows == 12
    assert result.missing_ids == 0
    assert result.duplicate_ids == 0
    assert result.extra_columns == ()
    assert all(count == 0 for count in result.cast_failures.values())


def test_bronze_keeps_rows_in_csv_order(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, data_config: DataConfig
) -> None:
    rows = bronze_rows(con, tmp_path, data_config)
    assert list(rows) == [f"E-{i:02d}" for i in range(1, 13)]


def test_bronze_types_follow_the_schema(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, data_config: DataConfig
) -> None:
    rows = bronze_rows(con, tmp_path, data_config)

    first = rows["E-01"]
    assert first["id_reclamacao"] == 1001
    assert first["data_abertura"] == datetime(2022, 3, 15, 14, 30)
    assert first["padronizada"] is True
    assert first["avaliacao_nota"] == 5
    assert "\n" in str(first["reclamacao_labeled"])
    assert '"PED-123"' in str(first["reclamacao_labeled"])

    assert rows["E-05"]["data_abertura"] == datetime(2024, 2, 10, 8)
    assert rows["E-06"]["data_abertura"] == datetime(2024, 8, 1)
    assert rows["E-08"]["data_abertura"] == datetime(2023, 12, 31)
    assert rows["E-07"]["data_abertura"] is None
    assert rows["E-07"]["avaliacao_nota"] is None


@pytest.mark.parametrize(
    ("row_id", "expected"),
    [
        ("E-01", True),  # sim
        ("E-02", True),  # 1
        ("E-03", True),  # True
        ("E-05", False),  # não
        ("E-06", False),  # 0
        ("E-10", False),  # FALSE
        ("E-11", False),  # f
        ("E-12", False),  # n
        ("E-07", None),  # empty
    ],
)
def test_boolean_tokens(
    con: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    data_config: DataConfig,
    row_id: str,
    expected: bool | None,
) -> None:
    assert bronze_rows(con, tmp_path, data_config)[row_id]["padronizada"] is expected


def test_missing_column_is_rejected(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    header = [name for name in RAW_COLUMN_NAMES if name != "data_abertura"]
    path = write_csv(tmp_path / "missing.csv", header, [["x"] * len(header)])

    with pytest.raises(SchemaError, match="data_abertura"):
        validate_csv(con, path, CsvConfig(), ValidationConfig())


def test_extra_columns_are_reported(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "extra.csv", [*RAW_COLUMN_NAMES, "nova_coluna"], [[*valid_row(1), "x"]]
    )
    result = validate_csv(con, path, CsvConfig(), ValidationConfig())
    assert result.extra_columns == ("nova_coluna",)


def test_too_many_cast_failures_stop_the_pipeline(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    rows = [valid_row(i) for i in range(9)] + [valid_row(9, data_abertura="ontem")]
    path = write_csv(tmp_path / "bad.csv", list(RAW_COLUMN_NAMES), rows)

    with pytest.raises(CastValidationError, match="data_abertura"):
        validate_csv(con, path, CsvConfig(), ValidationConfig(max_cast_failure_rate=0.05))


def test_cast_failures_below_threshold_are_counted(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    rows = [valid_row(i) for i in range(9)] + [valid_row(9, avaliacao_nota="5.5")]
    path = write_csv(tmp_path / "some_bad.csv", list(RAW_COLUMN_NAMES), rows)

    result = validate_csv(con, path, CsvConfig(), ValidationConfig(max_cast_failure_rate=0.2))

    assert result.cast_failures["avaliacao_nota"] == 1
    assert result.non_null["avaliacao_nota"] == 10


def test_duplicate_ids_are_counted(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    rows = [valid_row(1), valid_row(2, ID="R-1")]
    path = write_csv(tmp_path / "dup_ids.csv", list(RAW_COLUMN_NAMES), rows)
    assert validate_csv(con, path, CsvConfig(), ValidationConfig()).duplicate_ids == 1
