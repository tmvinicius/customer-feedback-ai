"""Typed views of `configs/data.yaml` and `configs/splits.yaml`."""

from datetime import date
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model

DATA_CONFIG_PATH = CONFIGS_DIR / "data.yaml"
SPLITS_CONFIG_PATH = CONFIGS_DIR / "splits.yaml"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CsvConfig(_Frozen):
    delimiter: str = "auto"
    quote: str = '"'
    escape: str = '"'
    timestamp_formats: tuple[str, ...] = ()


class ValidationConfig(_Frozen):
    max_cast_failure_rate: float = Field(default=0.01, ge=0, le=1)


class SampleConfig(_Frozen):
    dev_sample_size: int = Field(default=50_000, gt=0)
    taxonomy_review_size: int = Field(default=200, gt=0)
    seed: int = 20260101


class DuckDBConfig(_Frozen):
    memory_limit: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?\s?[KMGT]i?B$")


class PaperReference(_Frozen):
    """Values reported by the ConsumerBR paper, used as sanity checks only."""

    tolerance: float = Field(gt=0, lt=1)
    records: int
    companies: int
    period_start: date
    period_end: date
    response_rate: float
    standardized_response_rate: float
    complaint_chars_mean: float
    complaint_chars_median: float
    complaints_per_company_median: float
    complaints_per_company_max: int
    missing_data_abertura: int
    missing_localizacao: int
    missing_status: int


class DataConfig(_Frozen):
    csv: CsvConfig = CsvConfig()
    validation: ValidationConfig = ValidationConfig()
    sample: SampleConfig = SampleConfig()
    duckdb: DuckDBConfig = DuckDBConfig()
    paper_reference: PaperReference | None = None


class Window(_Frozen):
    """Inclusive date window. `None` leaves that side open."""

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            msg = f"window start {self.start} is after end {self.end}"
            raise ValueError(msg)
        return self


class SplitWindows(_Frozen):
    train: Window
    val: Window
    test: Window

    @model_validator(mode="after")
    def _chronological(self) -> Self:
        if self.train.end is None or self.val.start is None or self.val.end is None:
            msg = "train.end, val.start and val.end must be set"
            raise ValueError(msg)
        if self.test.start is None:
            msg = "test.start must be set"
            raise ValueError(msg)
        if not self.train.end < self.val.start or not self.val.end < self.test.start:
            msg = "windows must be chronological and must not overlap: train < val < test"
            raise ValueError(msg)
        return self


class HoldoutConfig(_Frozen):
    fraction: float = Field(gt=0, lt=1)
    salt: str = Field(min_length=1)


class SplitsConfig(_Frozen):
    windows: SplitWindows
    holdout_companies: HoldoutConfig


def load_data_config(path: Path = DATA_CONFIG_PATH) -> DataConfig:
    return load_yaml_model(path, DataConfig)


def load_splits_config(path: Path = SPLITS_CONFIG_PATH) -> SplitsConfig:
    return load_yaml_model(path, SplitsConfig)
