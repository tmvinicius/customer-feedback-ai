"""Message Batches backend on the Anthropic SDK.

Each request asks for structured output (`output_config.format`) so the reply is
JSON that follows the label schema. Results are matched by `custom_id`, never by
position, because batches return them in any order.
"""

from collections.abc import Iterator, Sequence
from typing import Any

import anthropic
from anthropic.types import OutputConfigParam
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage


def build_params(request: LLMRequest) -> MessageCreateParamsNonStreaming:
    params: MessageCreateParamsNonStreaming = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": (
            [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]
            if request.cache_system
            else request.system
        ),
        "messages": [{"role": "user", "content": request.user}],
    }
    output_config: OutputConfigParam = {}
    if request.effort is not None:
        output_config["effort"] = request.effort
    if request.json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
    if output_config:
        params["output_config"] = output_config
    return params


def to_result(custom_id: str, result: Any) -> LLMResult:
    """Map one SDK batch result to an `LLMResult`."""
    kind = result.type
    if kind != "succeeded":
        error = getattr(getattr(result, "error", None), "type", None)
        return LLMResult(custom_id=custom_id, status=kind, error=str(error) if error else kind)
    message = result.message
    usage = TokenUsage(
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cache_creation_input_tokens=message.usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=message.usage.cache_read_input_tokens or 0,
    )
    if message.stop_reason == "refusal":
        return LLMResult(custom_id=custom_id, status="refused", usage=usage, error="refusal")
    if message.stop_reason == "max_tokens":
        return LLMResult(custom_id=custom_id, status="truncated", usage=usage, error="max_tokens")
    text = next((block.text for block in message.content if block.type == "text"), None)
    return LLMResult(custom_id=custom_id, status="succeeded", text=text, usage=usage)


class AnthropicBatchClient:
    """`BatchLLMClient` backed by the Message Batches API."""

    def __init__(self, sdk: anthropic.Anthropic | None = None, api_key: str | None = None):
        self._sdk = sdk or anthropic.Anthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def is_external(self) -> bool:
        return True

    def submit_batch(self, requests: Sequence[LLMRequest]) -> str:
        batch = self._sdk.messages.batches.create(
            requests=[
                Request(custom_id=request.custom_id, params=build_params(request))
                for request in requests
            ]
        )
        return batch.id

    def batch_ended(self, batch_id: str) -> bool:
        return self._sdk.messages.batches.retrieve(batch_id).processing_status == "ended"

    def batch_results(self, batch_id: str) -> Iterator[LLMResult]:
        for item in self._sdk.messages.batches.results(batch_id):
            yield to_result(item.custom_id, item.result)
