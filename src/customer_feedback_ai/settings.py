"""Project settings read from environment variables and the local `.env` file.

Every field maps to an upper-case environment variable with the same name
(for example, `llm_model_cheap` reads `LLM_MODEL_CHEAP`). `.env.example`
documents all of them, and a unit test keeps both in sync.

Relative paths are resolved against the current working directory, which is
the repository root when commands run through the Makefile.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets stay in `.env`, never in Git."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    anthropic_api_key: SecretStr | None = None

    llm_model_cheap: str = "claude-haiku-5-5"
    llm_model_premium: str = "claude-sonnet-5-5"
    llm_model_draft: str = "claude-sonnet-5-5"

    llm_budget_usd: float = Field(default=30.0, gt=0)
    llm_job_approval_threshold_usd: float = Field(default=5.0, gt=0)

    # Sending corpus text to an external LLM needs human decision G1 (AGENTS.md, rule 10).
    allow_external_llm: bool = False

    # Identifies who wrote each gold label (AGENTS.md, section 7).
    annotator_id: str = Field(default="anotador_1", min_length=1)

    cases_index: Literal["synthetic", "real"] = "synthetic"

    data_dir: Path = Path("data")

    @model_validator(mode="after")
    def _approval_threshold_within_budget(self) -> Self:
        if self.llm_job_approval_threshold_usd > self.llm_budget_usd:
            msg = (
                "LLM_JOB_APPROVAL_THRESHOLD_USD "
                f"({self.llm_job_approval_threshold_usd}) must not exceed "
                f"LLM_BUDGET_USD ({self.llm_budget_usd})"
            )
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
