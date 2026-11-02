"""Provider-neutral request and result types for LLM calls."""

from dataclasses import dataclass
from typing import Any, Literal

Effort = Literal["low", "medium", "high", "xhigh", "max"]
ResultStatus = Literal["succeeded", "refused", "truncated", "errored", "expired", "canceled"]


@dataclass(frozen=True)
class LLMRequest:
    """One classification-style request: a system prompt and one user message."""

    custom_id: str
    model: str
    system: str
    user: str
    max_tokens: int
    effort: Effort | None = None
    json_schema: dict[str, Any] | None = None
    # Mark the system prompt for prompt caching. It does not change the answer.
    cache_system: bool = False


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """All input tokens of the request, which decide the price tier."""
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


@dataclass(frozen=True)
class LLMResult:
    custom_id: str
    status: ResultStatus
    text: str | None = None
    usage: TokenUsage | None = None
    error: str | None = None
