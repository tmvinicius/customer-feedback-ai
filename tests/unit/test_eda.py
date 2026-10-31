"""Lean profile and the comparison with the paper's reference values."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from customer_feedback_ai.data.config import DataConfig, PaperReference
from customer_feedback_ai.data.eda import compare_with_paper, profile
from customer_feedback_ai.data.ingest import write_bronze

from .conftest import EDGE_CASES_CSV


@pytest.fixture
def edge_profile(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, data_config: DataConfig
) -> dict[str, object]:
    bronze = tmp_path / "bronze.parquet"
    write_bronze(con, EDGE_CASES_CSV, bronze, data_config.csv)
    return profile(con, bronze)


def test_profile_counts(edge_profile: dict[str, object]) -> None:
    assert edge_profile["rows"] == 12
    assert edge_profile["companies"] == 5
    assert edge_profile["period"] == {"start": "2022-03-15", "end": "2025-04-30"}
    missing = edge_profile["missing"]
    assert isinstance(missing, dict)
    assert missing["data_abertura"] == 2
    assert missing["resposta_labeled"] == 2
    assert missing["ID"] == 0


def test_profile_has_no_complaint_text(edge_profile: dict[str, object]) -> None:
    assert "geladeira" not in str(edge_profile).lower()


def reference(**overrides: object) -> PaperReference:
    values: dict[str, object] = {
        "tolerance": 0.02,
        "records": 100,
        "companies": 10,
        "period_start": date(2021, 5, 1),
        "period_end": date(2025, 4, 30),
        "response_rate": 0.9,
        "standardized_response_rate": 0.9,
        "complaint_chars_mean": 500,
        "complaint_chars_median": 400,
        "complaints_per_company_median": 10,
        "complaints_per_company_max": 50,
        "missing_data_abertura": 10,
        "missing_localizacao": 10,
        "missing_status": 10,
    }
    return PaperReference.model_validate(values | overrides)


def test_comparison_flags_values_outside_tolerance(edge_profile: dict[str, object]) -> None:
    comparison = {item["metric"]: item for item in compare_with_paper(edge_profile, reference())}

    assert comparison["records"]["observed"] == 12
    assert comparison["records"]["relative_diff"] == pytest.approx(-0.88)
    assert comparison["records"]["within_tolerance"] is False
    assert comparison["period_end"]["within_tolerance"] is True
    assert comparison["period_start"]["within_tolerance"] is False


def test_comparison_accepts_values_within_tolerance(edge_profile: dict[str, object]) -> None:
    comparison = compare_with_paper(edge_profile, reference(records=12, companies=5))
    by_metric = {item["metric"]: item for item in comparison}
    assert by_metric["records"]["within_tolerance"] is True
    assert by_metric["companies"]["within_tolerance"] is True
