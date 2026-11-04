"""The interface every LLM backend implements.

Pipelines depend on this protocol, never on a provider SDK, so tests run with
`FakeLLM` and never call a real API (AGENTS.md, section 11).
"""

from collections.abc import Iterator, Sequence
from typing import Any, Protocol

from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.llm.types import LLMRequest, LLMResult


class StaleBatchError(DataPipelineError):
    """The backend does not know this batch, for example after a restart of a local run."""


class BatchLLMClient(Protocol):
    @property
    def name(self) -> str:
        """Backend name. Caches and logs are kept apart per backend."""
        ...

    @property
    def is_external(self) -> bool:
        """True when requests leave the machine, which requires G1."""
        ...

    def submit_batch(self, requests: Sequence[LLMRequest]) -> str:
        """Submit requests for asynchronous processing and return the batch id."""
        ...

    def batch_ended(self, batch_id: str) -> bool:
        """Raises `StaleBatchError` when the backend does not know the batch."""
        ...

    def batch_results(self, batch_id: str) -> Iterator[LLMResult]:
        """Results of an ended batch, in any order."""
        ...


class ChatClient(Protocol):
    """A local backend answered one request at a time, as the triage needs."""

    @property
    def name(self) -> str: ...

    def chat(self, request: LLMRequest) -> LLMResult: ...

    def missing_models(self, tags: Sequence[str]) -> list[str]: ...

    def model_details(self, tag: str) -> dict[str, Any]: ...

    def memory_snapshot(self, tag: str) -> dict[str, Any] | None: ...
