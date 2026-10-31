"""Raw CSV to bronze Parquet: typed columns, no business rules.

The CSV is read with every column as text and cast with explicit rules, so a
value that does not fit its type becomes NULL and is counted. The pipeline
stops when too many values of a column fail, instead of writing corrupted data.
Error messages carry column names and counts, never complaint text.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from customer_feedback_ai.data.config import CsvConfig, ValidationConfig
from customer_feedback_ai.data.schema import RAW_COLUMN_NAMES, RAW_COLUMNS, ColumnType
from customer_feedback_ai.data.sql import ident, list_literal, literal
from customer_feedback_ai.errors import DataPipelineError

TRUE_TOKENS = ("true", "t", "1", "sim", "s", "yes", "y")
FALSE_TOKENS = ("false", "f", "0", "nao", "n", "no")

_RAW_VIEW = "raw_csv"


class SchemaError(DataPipelineError):
    """The CSV does not have the expected columns."""


class CastValidationError(DataPipelineError):
    """Too many values of a column could not be cast to the expected type."""


@dataclass(frozen=True)
class IngestResult:
    rows: int
    missing_ids: int
    duplicate_ids: int
    non_null: dict[str, int]
    cast_failures: dict[str, int]
    extra_columns: tuple[str, ...]


def _scalar_source(column: str) -> str:
    return f"nullif(trim({ident(column)}), '')"


def typed_expression(
    column: str, column_type: ColumnType, timestamp_formats: tuple[str, ...]
) -> str:
    """Cast one raw text column to its expected type. Invalid values become NULL."""
    if column_type is ColumnType.TEXT:
        return ident(column)
    src = _scalar_source(column)
    if column_type is ColumnType.INTEGER:
        # DuckDB rounds '5.5' to 6 when casting text to BIGINT, so only plain
        # integers and integral decimals such as '5.0' are accepted.
        as_double = f"try_cast({src} AS DOUBLE)"
        return (
            f"CASE WHEN regexp_full_match({src}, '[+-]?[0-9]+') THEN try_cast({src} AS BIGINT) "
            f"WHEN {as_double} = round({as_double}) THEN try_cast({as_double} AS BIGINT) END"
        )
    if column_type is ColumnType.BOOLEAN:
        token = f"strip_accents(lower({src}))"
        return (
            f"CASE WHEN {token} IN {_tuple_literal(TRUE_TOKENS)} THEN true "
            f"WHEN {token} IN {_tuple_literal(FALSE_TOKENS)} THEN false END"
        )
    parsed = f"try_cast({src} AS TIMESTAMP)"
    if timestamp_formats:
        parsed = f"coalesce({parsed}, try_strptime({src}, {list_literal(timestamp_formats)}))"
    return parsed


def _tuple_literal(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(literal(value) for value in values) + ")"


def _read_csv_sql(csv_path: Path, config: CsvConfig) -> str:
    options = [
        "header = true",
        "all_varchar = true",
        f"quote = {literal(config.quote)}",
        f"escape = {literal(config.escape)}",
    ]
    if config.delimiter != "auto":
        options.append(f"delim = {literal(config.delimiter)}")
    return f"read_csv({literal(csv_path)}, {', '.join(options)})"


def _register_raw(con: duckdb.DuckDBPyConnection, csv_path: Path, config: CsvConfig) -> list[str]:
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW {_RAW_VIEW} AS "
        f"SELECT * FROM {_read_csv_sql(csv_path, config)}"
    )
    return [str(row[0]) for row in con.execute(f"DESCRIBE {_RAW_VIEW}").fetchall()]


def _check_columns(columns: list[str]) -> tuple[str, ...]:
    missing = [name for name in RAW_COLUMN_NAMES if name not in columns]
    if missing:
        msg = f"CSV is missing expected columns: {missing}. Found: {columns}"
        raise SchemaError(msg)
    return tuple(name for name in columns if name not in RAW_COLUMN_NAMES)


def validate_csv(
    con: duckdb.DuckDBPyConnection,
    csv_path: Path,
    csv_config: CsvConfig,
    validation: ValidationConfig,
) -> IngestResult:
    """Check columns and cast rules without writing anything."""
    extra = _check_columns(_register_raw(con, csv_path, csv_config))

    measures = ["count(*)", f"count({ident('ID')})", f"count(DISTINCT {ident('ID')})"]
    for column in RAW_COLUMNS:
        source = (
            ident(column.name) if column.type is ColumnType.TEXT else _scalar_source(column.name)
        )
        typed = typed_expression(column.name, column.type, csv_config.timestamp_formats)
        measures.append(f"count({source})")
        measures.append(f"count(*) FILTER (WHERE ({source}) IS NOT NULL AND ({typed}) IS NULL)")

    row = con.execute(f"SELECT {', '.join(measures)} FROM {_RAW_VIEW}").fetchone()
    assert row is not None
    rows, ids, distinct_ids, *per_column = (int(value) for value in row)
    non_null = {column.name: per_column[2 * i] for i, column in enumerate(RAW_COLUMNS)}
    failures = {column.name: per_column[2 * i + 1] for i, column in enumerate(RAW_COLUMNS)}

    if rows == 0:
        msg = f"{csv_path.name} has no rows"
        raise CastValidationError(msg)
    too_many = {
        name: f"{count}/{non_null[name]}"
        for name, count in failures.items()
        if non_null[name] and count / non_null[name] > validation.max_cast_failure_rate
    }
    if too_many:
        msg = (
            f"cast failures above {validation.max_cast_failure_rate:.2%} per column: {too_many}. "
            "Check the formats in configs/data.yaml."
        )
        raise CastValidationError(msg)

    return IngestResult(
        rows=rows,
        missing_ids=rows - ids,
        duplicate_ids=ids - distinct_ids,
        non_null=non_null,
        cast_failures=failures,
        extra_columns=extra,
    )


def write_bronze(
    con: duckdb.DuckDBPyConnection,
    csv_path: Path,
    output: Path,
    csv_config: CsvConfig,
) -> None:
    """Write the typed bronze table in the original CSV row order."""
    _check_columns(_register_raw(con, csv_path, csv_config))
    selects = ", ".join(
        typed_expression(column.name, column.type, csv_config.timestamp_formats)
        + f" AS {ident(column.name)}"
        for column in RAW_COLUMNS
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY (SELECT {selects} FROM {_RAW_VIEW}) TO {literal(output)} "
        "(FORMAT parquet, COMPRESSION zstd)"
    )
