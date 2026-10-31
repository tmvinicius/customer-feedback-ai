"""Topic and urgency taxonomy loaded from `configs/taxonomy.yaml` (AGENTS.md, section 7)."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model

TAXONOMY_PATH = CONFIGS_DIR / "taxonomy.yaml"
FALLBACK_TOPIC = "outro"
URGENCY_LEVELS: tuple[str, ...] = ("baixa", "media", "alta")


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)


class Taxonomy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    topics: tuple[Label, ...]
    urgency: tuple[Label, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        topic_ids = [topic.id for topic in self.topics]
        if len(set(topic_ids)) != len(topic_ids):
            msg = f"duplicate topic ids: {topic_ids}"
            raise ValueError(msg)
        if FALLBACK_TOPIC not in topic_ids:
            msg = f"the taxonomy needs the fallback topic '{FALLBACK_TOPIC}'"
            raise ValueError(msg)
        urgency_ids = tuple(level.id for level in self.urgency)
        if urgency_ids != URGENCY_LEVELS:
            msg = f"urgency levels must be {URGENCY_LEVELS}, in this order; got {urgency_ids}"
            raise ValueError(msg)
        return self

    @property
    def topic_ids(self) -> tuple[str, ...]:
        return tuple(topic.id for topic in self.topics)

    @property
    def urgency_ids(self) -> tuple[str, ...]:
        return tuple(level.id for level in self.urgency)


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    return load_yaml_model(path, Taxonomy)
