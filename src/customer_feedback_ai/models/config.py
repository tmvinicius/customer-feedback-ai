"""Typed views of `configs/rules.yaml` (B1) and `configs/train.yaml` (C1 and measurements)."""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model

RULES_PATH = CONFIGS_DIR / "rules.yaml"
TRAIN_CONFIG_PATH = CONFIGS_DIR / "train.yaml"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TopicRule(_Frozen):
    id: str
    keywords: tuple[str, ...] = Field(min_length=1)


class UrgencyRules(_Frozen):
    default: Literal["baixa", "media", "alta"] = "media"
    alta: tuple[str, ...] = ()
    baixa: tuple[str, ...] = ()


class RulesConfig(_Frozen):
    version: str
    fallback_topic: str
    topics: tuple[TopicRule, ...]
    urgency: UrgencyRules

    @model_validator(mode="after")
    def _unique_topics(self) -> Self:
        ids = [rule.id for rule in self.topics]
        if len(set(ids)) != len(ids):
            msg = f"duplicate topic rules: {ids}"
            raise ValueError(msg)
        return self


class C1Config(_Frozen):
    word_ngrams: tuple[int, int] = (1, 2)
    char_ngrams: tuple[int, int] = (3, 5)
    min_df: int = Field(default=2, ge=1)
    max_features_word: int = Field(default=200_000, gt=0)
    max_features_char: int = Field(default=300_000, gt=0)
    c_grid: tuple[float, ...] = Field(default=(0.25, 1.0, 4.0), min_length=1)
    class_weight: Literal["balanced"] | None = "balanced"
    max_iter: int = Field(default=2000, gt=0)


class MeasurementConfig(_Frozen):
    latency_samples: int = Field(default=300, gt=0)
    bootstrap_resamples: int = Field(default=1000, gt=0)


class TrainConfig(_Frozen):
    seed: int = 20261104
    c1: C1Config = C1Config()
    measurement: MeasurementConfig = MeasurementConfig()


def load_rules(path: Path = RULES_PATH) -> RulesConfig:
    return load_yaml_model(path, RulesConfig)


def load_train_config(path: Path = TRAIN_CONFIG_PATH) -> TrainConfig:
    return load_yaml_model(path, TrainConfig)
