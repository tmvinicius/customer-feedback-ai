"""Bronze to silver: cleaned, normalized and deduplicated complaints.

- Complaint, response and comment texts get Unicode NFC and trimmed ends.
  Anonymization tags such as `[NOME]` are kept as they are.
- Company, location and status get collapsed whitespace.
- Rows without complaint text are dropped.
- Exact duplicates, by the hash of the normalized complaint text, keep only the
  oldest occurrence. Rows with a date win over rows without one, so a duplicate
  never moves a text out of the splits.
- `loose_hash` groups texts that differ only by digits, punctuation, accents or
  tags. It is kept to measure near-duplicates, not to drop rows.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.schema import (
    COMPANY_KEY_COLUMN,
    LOOSE_HASH_COLUMN,
    RAW_COLUMNS,
    TEXT_COLUMN,
    TEXT_HASH_COLUMN,
)

LONG_TEXT_COLUMNS = ("reclamacao_labeled", "resposta_labeled", "avaliacao_comentario")
SHORT_TEXT_COLUMNS = ("empresa", "localizacao", "status")

# Oldest first; the remaining columns only break ties deterministically.
_OCCURRENCE_ORDER = ", ".join(
    [f"{sql.ident(name)} NULLS LAST" for name in ("data_abertura", "id_reclamacao", "ID")]
    + [
        f"{sql.ident(column.name)} NULLS LAST"
        for column in RAW_COLUMNS
        if column.name not in ("data_abertura", "id_reclamacao", "ID")
    ]
)


@dataclass(frozen=True)
class SilverResult:
    rows_in: int
    dropped_empty_text: int
    dropped_duplicates: int
    duplicate_groups: int
    rows_out: int
    loose_duplicate_rows: int
    loose_duplicate_groups: int


def _cleaned_columns() -> str:
    parts = []
    for column in RAW_COLUMNS:
        name = sql.ident(column.name)
        if column.name in LONG_TEXT_COLUMNS:
            parts.append(f"{sql.clean_long_text(name)} AS {name}")
        elif column.name in SHORT_TEXT_COLUMNS:
            parts.append(f"{sql.clean_short_text(name)} AS {name}")
        else:
            parts.append(name)
    return ", ".join(parts)


def build_silver(con: duckdb.DuckDBPyConnection, bronze: Path, output: Path) -> SilverResult:
    text = sql.ident(TEXT_COLUMN)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE silver_keyed AS
        WITH cleaned AS (
            SELECT {_cleaned_columns()} FROM read_parquet({sql.literal(bronze)})
        )
        SELECT
            *,
            {sql.sha256_of(sql.dedup_key(text))} AS {TEXT_HASH_COLUMN},
            {sql.sha256_of(sql.loose_key(text))} AS {LOOSE_HASH_COLUMN},
            {sql.company_key(sql.ident("empresa"))} AS {COMPANY_KEY_COLUMN}
        FROM cleaned
        WHERE {text} IS NOT NULL
        """
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT * EXCLUDE (occurrence) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY {TEXT_HASH_COLUMN} ORDER BY {_OCCURRENCE_ORDER}
                ) AS occurrence
                FROM silver_keyed
            )
            WHERE occurrence = 1
            ORDER BY data_abertura NULLS LAST, {TEXT_HASH_COLUMN}
        ) TO {sql.literal(output)} (FORMAT parquet, COMPRESSION zstd)
        """
    )

    rows_in = _scalar(con, f"SELECT count(*) FROM read_parquet({sql.literal(bronze)})")
    kept_text = _scalar(con, "SELECT count(*) FROM silver_keyed")
    groups = _scalar(
        con,
        f"SELECT count(*) FROM (SELECT {TEXT_HASH_COLUMN} FROM silver_keyed "
        f"GROUP BY 1 HAVING count(*) > 1)",
    )
    rows_out = _scalar(con, f"SELECT count(*) FROM read_parquet({sql.literal(output)})")
    loose_rows, loose_groups = _loose_duplicates(con, output)
    con.execute("DROP TABLE silver_keyed")

    return SilverResult(
        rows_in=rows_in,
        dropped_empty_text=rows_in - kept_text,
        dropped_duplicates=kept_text - rows_out,
        duplicate_groups=groups,
        rows_out=rows_out,
        loose_duplicate_rows=loose_rows,
        loose_duplicate_groups=loose_groups,
    )


def _loose_duplicates(con: duckdb.DuckDBPyConnection, silver: Path) -> tuple[int, int]:
    row = con.execute(
        f"""
        SELECT coalesce(sum(n), 0), count(*) FROM (
            SELECT count(*) AS n FROM read_parquet({sql.literal(silver)})
            WHERE {LOOSE_HASH_COLUMN} IS NOT NULL
            GROUP BY {LOOSE_HASH_COLUMN} HAVING count(*) > 1
        )
        """
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _scalar(con: duckdb.DuckDBPyConnection, query: str) -> int:
    row = con.execute(query).fetchone()
    assert row is not None
    return int(row[0])
