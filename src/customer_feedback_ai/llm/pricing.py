"""Token prices from `configs/pricing.yaml` and the cost of a call."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from customer_feedback_ai.config import CONFIGS_DIR, load_yaml_model
from customer_feedback_ai.llm.types import TokenUsage

PRICING_PATH = CONFIGS_DIR / "pricing.yaml"
_MILLION = 1_000_000


class ModelPrices(BaseModel):
    """US$ per million tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_prompt_tokens: int | None = None
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_write_5m: float = Field(ge=0)
    cache_read: float = Field(ge=0)


class Pricing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checked_at: date
    source: str
    batch_discount: float = Field(gt=0, le=1)
    models: dict[str, ModelPrices]

    def prices(self, model: str) -> ModelPrices:
        if model not in self.models:
            msg = f"no price for model {model!r} in configs/pricing.yaml"
            raise KeyError(msg)
        return self.models[model]

    def cost_usd(self, model: str, usage: TokenUsage, *, batch: bool) -> float:
        """Cost of one call. Refuses prompts above the priced tier instead of guessing."""
        prices = self.prices(model)
        if prices.max_prompt_tokens is not None and usage.prompt_tokens > prices.max_prompt_tokens:
            msg = (
                f"prompt of {usage.prompt_tokens} tokens is above the priced tier of {model} "
                f"({prices.max_prompt_tokens}); add the higher prices to configs/pricing.yaml"
            )
            raise ValueError(msg)
        total = (
            usage.input_tokens * prices.input
            + usage.output_tokens * prices.output
            + usage.cache_creation_input_tokens * prices.cache_write_5m
            + usage.cache_read_input_tokens * prices.cache_read
        ) / _MILLION
        return total * (self.batch_discount if batch else 1.0)


def load_pricing(path: Path = PRICING_PATH) -> Pricing:
    return load_yaml_model(path, Pricing)
