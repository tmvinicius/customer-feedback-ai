"""Lean data profile: missing values, sizes, distributions per company and status.

The profile holds only aggregates. Company names appear in the top list, but no
complaint or response text is ever included.
"""

from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.config import PaperReference
from customer_feedback_ai.data.schema import RAW_COLUMN_NAMES, TEXT_COLUMN

TOP_COMPANIES = 10


def _one(con: duckdb.DuckDBPyConnection, query: str) -> tuple[Any, ...]:
    row = con.execute(query).fetchone()
    assert row is not None
    return tuple(row)


def _round(value: Any, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _length_stats(con: duckdb.DuckDBPyConnection, source: str, column: str) -> dict[str, Any]:
    length = f"length({sql.ident(column)})"
    count, mean, median, p95, maximum = _one(
        con,
        f"SELECT count({length}), avg({length}), quantile_cont({length}, 0.5), "
        f"quantile_cont({length}, 0.95), max({length}) FROM {source}",
    )
    return {
        "count": int(count),
        "mean": _round(mean, 1),
        "median": _round(median, 1),
        "p95": _round(p95, 1),
        "max": None if maximum is None else int(maximum),
    }


def profile(con: duckdb.DuckDBPyConnection, parquet: Path) -> dict[str, Any]:
    """Aggregate statistics of a bronze or silver table."""
    source = f"read_parquet({sql.literal(parquet)})"
    rows, companies, start, end = _one(
        con,
        f"SELECT count(*), count(DISTINCT empresa), min(CAST(data_abertura AS DATE)), "
        f"max(CAST(data_abertura AS DATE)) FROM {source}",
    )
    rows = int(rows)
    missing = {
        name: int(value)
        for name, value in zip(
            RAW_COLUMN_NAMES,
            _one(
                con,
                "SELECT "
                + ", ".join(f"count(*) - count({sql.ident(n)})" for n in RAW_COLUMN_NAMES)
                + f" FROM {source}",
            ),
            strict=True,
        )
    }
    responses, standardized = _one(
        con, f"SELECT count(resposta_labeled), count(*) FILTER (WHERE padronizada) FROM {source}"
    )
    per_company = _one(
        con,
        "SELECT quantile_cont(n, 0.5), quantile_cont(n, 0.9), max(n), "
        "count(*) FILTER (WHERE n = 1) "
        f"FROM (SELECT count(*) AS n FROM {source} WHERE empresa IS NOT NULL GROUP BY empresa)",
    )
    top = con.execute(
        f"SELECT empresa, count(*) AS n FROM {source} WHERE empresa IS NOT NULL "
        f"GROUP BY empresa ORDER BY n DESC, empresa LIMIT {TOP_COMPANIES}"
    ).fetchall()

    return {
        "rows": rows,
        "companies": int(companies),
        "period": {"start": _iso(start), "end": _iso(end)},
        "missing": missing,
        "response_rate": _round(int(responses) / rows if rows else None),
        "standardized_share_of_responses": _round(
            int(standardized) / int(responses) if responses else None
        ),
        "standardized_share_of_rows": _round(int(standardized) / rows if rows else None),
        "complaint_chars": _length_stats(con, source, TEXT_COLUMN),
        "response_chars": _length_stats(con, source, "resposta_labeled"),
        "complaints_per_company": {
            "median": _round(per_company[0], 1),
            "p90": _round(per_company[1], 1),
            "max": None if per_company[2] is None else int(per_company[2]),
            "companies_with_one_complaint": int(per_company[3]),
        },
        "top_companies": [{"empresa": str(name), "rows": int(n)} for name, n in top],
        "status": _distribution(con, source, "status"),
        "avaliacao_nota": _distribution(con, source, "avaliacao_nota"),
        "padronizada": _distribution(con, source, "padronizada"),
    }


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _distribution(con: duckdb.DuckDBPyConnection, source: str, column: str) -> list[dict[str, Any]]:
    rows = con.execute(
        f"SELECT CAST({sql.ident(column)} AS VARCHAR) AS value, count(*) AS n FROM {source} "
        "GROUP BY 1 ORDER BY n DESC, value NULLS LAST"
    ).fetchall()
    return [{"value": value, "rows": int(n)} for value, n in rows]


def compare_with_paper(observed: dict[str, Any], reference: PaperReference) -> list[dict[str, Any]]:
    """Relative difference between the observed profile and the paper's values.

    `within_tolerance` is a sanity signal, not a pass or fail: divergences are
    documented in docs/data_card.md.
    """
    pairs: list[tuple[str, float, Any]] = [
        ("records", reference.records, observed["rows"]),
        ("companies", reference.companies, observed["companies"]),
        ("response_rate", reference.response_rate, observed["response_rate"]),
        (
            "standardized_response_rate",
            reference.standardized_response_rate,
            observed["standardized_share_of_responses"],
        ),
        (
            "complaint_chars_mean",
            reference.complaint_chars_mean,
            observed["complaint_chars"]["mean"],
        ),
        (
            "complaint_chars_median",
            reference.complaint_chars_median,
            observed["complaint_chars"]["median"],
        ),
        (
            "complaints_per_company_median",
            reference.complaints_per_company_median,
            observed["complaints_per_company"]["median"],
        ),
        (
            "complaints_per_company_max",
            reference.complaints_per_company_max,
            observed["complaints_per_company"]["max"],
        ),
        (
            "missing_data_abertura",
            reference.missing_data_abertura,
            observed["missing"]["data_abertura"],
        ),
        ("missing_localizacao", reference.missing_localizacao, observed["missing"]["localizacao"]),
        ("missing_status", reference.missing_status, observed["missing"]["status"]),
    ]
    comparison = []
    for metric, expected, value in pairs:
        diff = None if value is None or expected == 0 else (float(value) - expected) / expected
        comparison.append(
            {
                "metric": metric,
                "paper": expected,
                "observed": value,
                "relative_diff": _round(diff),
                "within_tolerance": diff is not None and abs(diff) <= reference.tolerance,
            }
        )
    for metric, expected_day, observed_day in (
        ("period_start", reference.period_start, observed["period"]["start"]),
        ("period_end", reference.period_end, observed["period"]["end"]),
    ):
        same_month = observed_day is not None and observed_day[:7] == expected_day.isoformat()[:7]
        comparison.append(
            {
                "metric": metric,
                "paper": expected_day.isoformat(),
                "observed": observed_day,
                "relative_diff": None,
                "within_tolerance": same_month,
            }
        )
    return comparison
