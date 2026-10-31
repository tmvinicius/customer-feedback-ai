"""Settings defaults follow AGENTS.md and stay in sync with `.env.example`."""

from pathlib import Path

import pytest
from pydantic import ValidationError

import customer_feedback_ai
from customer_feedback_ai.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_VARS = sorted(name.upper() for name in Settings.model_fields)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's shell variables out of the tests."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def load_settings() -> Settings:
    """Build settings without reading a local `.env`."""
    return Settings(_env_file=None)


def read_env_example() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep, f"invalid line in .env.example: {raw_line!r}"
        entries[key.strip()] = value.strip()
    return entries


def test_package_exposes_version() -> None:
    assert customer_feedback_ai.__version__


def test_defaults_follow_plan() -> None:
    settings = load_settings()

    assert settings.anthropic_api_key is None
    assert settings.llm_model_cheap == "claude-haiku-5-5"
    assert settings.llm_model_premium == "claude-sonnet-5-5"
    assert settings.llm_model_draft == "claude-sonnet-5-5"
    assert settings.llm_budget_usd == 30.0
    assert settings.llm_job_approval_threshold_usd == 5.0
    assert settings.cases_index == "synthetic"
    assert settings.data_dir == Path("data")


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL_CHEAP", "another-model")
    monkeypatch.setenv("CASES_INDEX", "real")
    monkeypatch.setenv("LLM_BUDGET_USD", "50")

    settings = load_settings()

    assert settings.llm_model_cheap == "another-model"
    assert settings.cases_index == "real"
    assert settings.llm_budget_usd == 50.0


def test_rejects_unknown_cases_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASES_INDEX", "production")

    with pytest.raises(ValidationError):
        load_settings()


def test_rejects_approval_threshold_above_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BUDGET_USD", "10")
    monkeypatch.setenv("LLM_JOB_APPROVAL_THRESHOLD_USD", "20")

    with pytest.raises(ValidationError, match="must not exceed"):
        load_settings()


def test_api_key_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")

    settings = load_settings()

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-test-secret"
    assert "sk-test-secret" not in repr(settings)


def test_env_example_documents_every_setting() -> None:
    assert sorted(read_env_example()) == ENV_VARS


def test_env_example_has_no_secret_values() -> None:
    assert read_env_example()["ANTHROPIC_API_KEY"] == ""
