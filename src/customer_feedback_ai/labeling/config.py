"""Typed view of `configs/labeling.yaml`."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model
from customer_feedback_ai.llm.types import Effort

LABELING_CONFIG_PATH = CONFIGS_DIR / "labeling.yaml"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldConfig(_Frozen):
    gold_dev_size: int = Field(gt=0)
    gold_test_size: int = Field(gt=0)
    gold_test_unseen_share: float = Field(ge=0, le=1)
    reannotation_fraction: float = Field(ge=0, le=1)
    reannotation_min_days: int = Field(ge=0)
    min_examples_per_topic_in_gold_dev: int = Field(ge=0)
    min_high_urgency_in_gold_test: int = Field(ge=0)
    seed: int


class SilverConfig(_Frozen):
    silver_train_size: int = Field(gt=0)
    silver_val_size: int = Field(gt=0)
    seed: int
    model_role: Literal["cheap", "premium"]
    prompt: Path
    effort: Effort | None = None
    max_tokens: int = Field(gt=0)
    cache_system_prompt: bool = True
    batch_chunk_size: int = Field(gt=0, le=100_000)
    chars_per_token: float = Field(gt=0)
    expected_output_tokens: int = Field(gt=0)


class LabelingConfig(_Frozen):
    gold: GoldConfig
    silver: SilverConfig


def load_labeling_config(path: Path = LABELING_CONFIG_PATH) -> LabelingConfig:
    return load_yaml_model(path, LabelingConfig)
