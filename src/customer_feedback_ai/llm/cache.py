"""Disk cache of successful LLM results, keyed by the full request.

The key covers model, system prompt, user message, token limit, effort and
schema, so any change to the prompt or parameters misses the cache. A rerun
never pays twice for the same request.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage


def request_key(request: LLMRequest) -> str:
    payload = {
        "model": request.model,
        "system": request.system,
        "user": request.user,
        "max_tokens": request.max_tokens,
        "effort": request.effort,
        "json_schema": request.json_schema,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResultCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, request: LLMRequest) -> Path:
        key = request_key(request)
        return self.directory / key[:2] / f"{key}.json"

    def get(self, request: LLMRequest) -> LLMResult | None:
        path = self._path(request)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        usage = TokenUsage(**data["usage"]) if data.get("usage") else None
        return LLMResult(
            custom_id=request.custom_id,
            status=data["status"],
            text=data.get("text"),
            usage=usage,
            error=data.get("error"),
        )

    def put(self, request: LLMRequest, result: LLMResult) -> None:
        if result.status != "succeeded":
            return
        path = self._path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload.pop("custom_id")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
