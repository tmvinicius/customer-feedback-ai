"""Typed views of `configs/rules.yaml` (B1) and `configs/train.yaml` (C1 and measurements)."""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model

RULES_PATH = CONFIGS_DIR / "rules.yaml"
TRAIN_CONFIG_PATH = CONFIGS_DIR / "train.yaml"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_keywords(keywords: tuple[str, ...]) -> tuple[str, ...]:
    for keyword in keywords:
        body = keyword.removesuffix("*")
        if not body.strip() or "*" in body:
            msg = f"invalid keyword {keyword!r}: use text, optionally ending in '*' for a stem"
            raise ValueError(msg)
    return keywords


class TopicRule(_Frozen):
    id: str
    keywords: tuple[str, ...] = Field(min_length=1)

    _valid = field_validator("keywords")(_check_keywords)


class UrgencyRules(_Frozen):
    default: Literal["baixa", "media", "alta"] = "media"
    alta: tuple[str, ...] = ()
    baixa: tuple[str, ...] = ()

    _valid = field_validator("alta", "baixa")(_check_keywords)


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


class C2Config(_Frozen):
    """Serafim sentence embeddings + one logistic regression per output."""

    encoder: str = "PORTULAN/serafim-100m-portuguese-pt-sentence-encoder-ir"
    # Hugging Face commit to pin the weights; null takes the latest and records its hash.
    revision: str | None = None
    batch_size: int = Field(default=32, gt=0)
    normalize: bool = True
    c_grid: tuple[float, ...] = Field(default=(0.25, 1.0, 4.0), min_length=1)
    class_weight: Literal["balanced"] | None = "balanced"
    max_iter: int = Field(default=2000, gt=0)


class C3Config(_Frozen):
    """BERTimbau fine-tuned with two classification heads (topic and urgency)."""

    encoder: str = "neuralmind/bert-base-portuguese-cased"
    revision: str | None = None
    max_length: int = Field(default=256, gt=8, le=512)
    batch_size: int = Field(default=16, gt=0)
    grad_accumulation: int = Field(default=1, gt=0)
    eval_batch_size: int = Field(default=64, gt=0)
    learning_rate: float = Field(default=2e-5, gt=0)
    weight_decay: float = Field(default=0.01, ge=0)
    warmup_ratio: float = Field(default=0.1, ge=0, lt=1)
    dropout: float = Field(default=0.1, ge=0, lt=1)
    epochs: int = Field(default=3, gt=0)
    # Early stopping on silver_val topic macro-F1: epochs without improvement.
    patience: int = Field(default=1, ge=0)
    class_weight: Literal["balanced"] | None = "balanced"
    # Training device; the measured inference always runs on CPU.
    device: Literal["auto", "cpu", "cuda"] = "auto"
    fp16: bool = True


class MeasurementConfig(_Frozen):
    latency_samples: int = Field(default=300, gt=0)
    bootstrap_resamples: int = Field(default=1000, gt=0)


class TrainConfig(_Frozen):
    seed: int = 20261104
    c1: C1Config = C1Config()
    c2: C2Config = C2Config()
    c3: C3Config = C3Config()
    measurement: MeasurementConfig = MeasurementConfig()


def load_rules(path: Path = RULES_PATH) -> RulesConfig:
    return load_yaml_model(path, RulesConfig)


def load_train_config(path: Path = TRAIN_CONFIG_PATH) -> TrainConfig:
    return load_yaml_model(path, TrainConfig)
