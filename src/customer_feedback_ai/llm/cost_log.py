"""Append-only log of LLM calls in `data/logs/llm_calls.jsonl`.

Each line holds tokens, cost, status and hashes. Complaint text is never
written here (AGENTS.md, section 12).
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CallRecord:
    experiment: str
    backend: str
    model: str
    custom_id: str
    status: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float
    batch: bool
    prompt_hash: str
    latency_s: float | None = None
    timestamp: str = ""


class CostLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, records: list[CallRecord]) -> None:
        if not records:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).isoformat()
        with self.path.open("a", encoding="utf-8") as handle:
            for record in records:
                payload = asdict(record)
                payload["timestamp"] = record.timestamp or now
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def spent_usd(self) -> float:
        """Total recorded spend, used to enforce the project budget."""
        return sum(float(str(record["cost_usd"])) for record in self.records())
