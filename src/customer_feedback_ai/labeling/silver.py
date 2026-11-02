"""Silver labels: LLM labels in batch for training the local models.

Sets:
- `silver_train`: up to 20,000 complaints from `train`.
- `silver_val`: 2,000 complaints from `val`, excluding the `gold_dev` items, so
  tuning on silver never touches the texts used to evaluate on gold.
- `gold_dev_llm`: the `gold_dev` items labeled by the same LLM, only to measure
  agreement with the human labels. They never become gold.

The job is a small state machine that survives restarts: each run submits what is
missing, collects ended batches, retries invalid replies once, and finally writes
the labels. Valid replies are cached, so nothing is paid for twice.

Guards before any paid submission (AGENTS.md, sections 3 and 16):
- an external client requires `ALLOW_EXTERNAL_LLM=true`, set only after G1;
- every paid run requires `CONFIRM_COST=1`;
- an estimate above the approval threshold requires an approved amount (G4) that
  covers it;
- the estimate plus what was already spent must fit in the project budget.
"""

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.schema import TEXT_COLUMN, TEXT_HASH_COLUMN
from customer_feedback_ai.data.splits import TRAIN, VAL
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.config import SilverConfig
from customer_feedback_ai.labeling.gold import GOLD_DEV, QueueItem
from customer_feedback_ai.labeling.output import LabelParseError, parse_label
from customer_feedback_ai.labeling.prompt import ClassificationPrompt
from customer_feedback_ai.labeling.taxonomy import Taxonomy
from customer_feedback_ai.llm.cache import ResultCache
from customer_feedback_ai.llm.client import BatchLLMClient
from customer_feedback_ai.llm.cost_log import CallRecord, CostLog
from customer_feedback_ai.llm.pricing import Pricing
from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage

SILVER_TRAIN, SILVER_VAL, GOLD_DEV_LLM = "silver_train", "silver_val", "gold_dev_llm"
SILVER_SETS: tuple[str, ...] = (SILVER_TRAIN, SILVER_VAL, GOLD_DEV_LLM)
MAX_ATTEMPTS = 2
JobStatus = Literal["submitted", "waiting", "done"]


class CostGuardError(DataPipelineError):
    """A paid run was blocked by a cost or authorization guard."""


@dataclass(frozen=True)
class SilverItem:
    set: str
    item_id: str
    source_id: str
    text: str


@dataclass(frozen=True)
class CostEstimate:
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class Authorization:
    """What the person running the job has authorized."""

    allow_external: bool = False
    confirm_cost: bool = False
    approved_usd: float | None = None


@dataclass
class _State:
    job_id: str
    model: str
    prompt_version: str
    prompt_sha256: str
    estimate: dict[str, Any]
    batches: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, dict[str, Any]] = field(default_factory=dict)


def _failure(attempt: int, status: str, error: str | None) -> dict[str, Any]:
    return {"attempt": attempt, "status": status, "error": error}


def _select(path: Path, set_name: str, n: int, seed: int, exclude: Sequence[str]) -> str:
    rank = f"sha256({sql.literal(f'{seed}:{set_name}:')} || {TEXT_HASH_COLUMN})"
    where = ""
    if exclude:
        where = f"WHERE {TEXT_HASH_COLUMN} NOT IN (SELECT item_id FROM silver_exclude)"
    return (
        f"SELECT '{set_name}', {TEXT_HASH_COLUMN}, CAST({sql.ident('ID')} AS VARCHAR), "
        f"{sql.ident(TEXT_COLUMN)} FROM read_parquet({sql.literal(path)}) {where} "
        f"ORDER BY {rank} LIMIT {int(n)}"
    )


def select_items(
    con: duckdb.DuckDBPyConnection,
    splits_dir: Path,
    queue: list[QueueItem],
    config: SilverConfig,
) -> list[SilverItem]:
    gold_dev = [item for item in queue if item.set == GOLD_DEV]
    if not gold_dev:
        msg = "the annotation queue has no gold_dev items. Run `make annotate` once first."
        raise DataPipelineError(msg)
    con.execute("CREATE OR REPLACE TEMP TABLE silver_exclude (item_id VARCHAR)")
    con.executemany("INSERT INTO silver_exclude VALUES (?)", [(i.item_id,) for i in gold_dev])
    rows = con.execute(
        _select(
            splits_dir / f"{TRAIN}.parquet", SILVER_TRAIN, config.silver_train_size, config.seed, []
        )
    ).fetchall()
    rows += con.execute(
        _select(
            splits_dir / f"{VAL}.parquet",
            SILVER_VAL,
            config.silver_val_size,
            config.seed,
            [i.item_id for i in gold_dev],
        )
    ).fetchall()
    items = [SilverItem(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]
    items += [SilverItem(GOLD_DEV_LLM, i.item_id, i.source_id, i.text) for i in gold_dev]
    return items


def build_request(
    item: SilverItem,
    prompt: ClassificationPrompt,
    schema: dict[str, Any],
    model: str,
    config: SilverConfig,
) -> LLMRequest:
    return LLMRequest(
        custom_id=item.item_id,
        model=model,
        system=prompt.system,
        user=prompt.user_message(item.text),
        max_tokens=config.max_tokens,
        effort=config.effort,
        json_schema=schema,
        cache_system=config.cache_system_prompt,
    )


def estimate_cost(
    requests: Sequence[LLMRequest], pricing: Pricing, config: SilverConfig
) -> CostEstimate:
    """Heuristic estimate before running: characters per token and fixed output size.

    Prompt-cache discounts are left out on purpose, so the estimate errs high.
    """
    if not requests:
        model = ""
        return CostEstimate(model=model, requests=0, input_tokens=0, output_tokens=0, cost_usd=0.0)
    model = requests[0].model
    input_tokens = output_tokens = 0
    cost = 0.0
    for request in requests:
        usage = TokenUsage(
            input_tokens=math.ceil(
                (len(request.system) + len(request.user)) / config.chars_per_token
            ),
            output_tokens=config.expected_output_tokens,
        )
        input_tokens += usage.input_tokens
        output_tokens += usage.output_tokens
        cost += pricing.cost_usd(model, usage, batch=True)
    return CostEstimate(model, len(requests), input_tokens, output_tokens, round(cost, 6))


def check_guards(
    client: BatchLLMClient,
    estimate: CostEstimate,
    auth: Authorization,
    spent_usd: float,
    budget_usd: float,
    approval_threshold_usd: float,
    *,
    retry: bool = False,
) -> None:
    """Raise `CostGuardError` unless the submission is authorized.

    A retry of invalid replies belongs to a job that was already confirmed, so it
    only rechecks G1 and the budget.
    """
    if not client.is_external:
        return
    if not auth.allow_external:
        msg = (
            "sending complaint text to an external LLM needs human decision G1. "
            "Set ALLOW_EXTERNAL_LLM=true only after G1 allows it."
        )
        raise CostGuardError(msg)
    summary = (
        f"{estimate.requests} requests to {estimate.model}, about {estimate.input_tokens} input "
        f"and {estimate.output_tokens} output tokens, estimated US$ {estimate.cost_usd:.2f} "
        "with the batch discount"
    )
    if spent_usd + estimate.cost_usd > budget_usd:
        msg = (
            f"{summary}; already spent US$ {spent_usd:.2f} of the US$ {budget_usd:.2f} budget. "
            "The job would exceed LLM_BUDGET_USD."
        )
        raise CostGuardError(msg)
    if retry:
        return
    if estimate.cost_usd > approval_threshold_usd and (
        auth.approved_usd is None or auth.approved_usd < estimate.cost_usd
    ):
        msg = (
            f"{summary}, above the US$ {approval_threshold_usd:.2f} approval threshold. "
            "Record the approval (G4) in docs/decisions.md and pass APPROVED_USD with the "
            "approved amount."
        )
        raise CostGuardError(msg)
    if not auth.confirm_cost:
        msg = f"{summary}. Run again with CONFIRM_COST=1 to submit."
        raise CostGuardError(msg)


class SilverJob:
    def __init__(
        self,
        *,
        items: list[SilverItem],
        prompt: ClassificationPrompt,
        taxonomy: Taxonomy,
        schema: dict[str, Any],
        model: str,
        config: SilverConfig,
        client: BatchLLMClient,
        pricing: Pricing,
        cache_dir: Path,
        cost_log: CostLog,
        state_path: Path,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.items = {item.item_id: item for item in items}
        if len(self.items) != len(items):
            msg = "silver items must have unique ids"
            raise DataPipelineError(msg)
        self.prompt, self.taxonomy, self.schema = prompt, taxonomy, schema
        self.model, self.config = model, config
        self.client, self.pricing, self.cost_log = client, pricing, cost_log
        # One cache per backend: offline answers must never stand in for real ones.
        self.cache = ResultCache(cache_dir / client.name)
        self.state_path = state_path
        self.now = now

    def request(self, item_id: str) -> LLMRequest:
        return build_request(self.items[item_id], self.prompt, self.schema, self.model, self.config)

    def pending(self) -> list[LLMRequest]:
        """Requests without a valid cached label."""
        requests = [self.request(item_id) for item_id in self.items]
        return [request for request in requests if self.cache.get(request) is None]

    # --- state -----------------------------------------------------------------

    def _load(self) -> _State | None:
        if not self.state_path.exists():
            return None
        return _State(**json.loads(self.state_path.read_text(encoding="utf-8")))

    def _save(self, state: _State) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")

    def _submit(self, state: _State, requests: list[LLMRequest], attempt: int) -> None:
        size = self.config.batch_chunk_size
        for start in range(0, len(requests), size):
            chunk = requests[start : start + size]
            batch_id = self.client.submit_batch(chunk)
            state.batches.append(
                {
                    "id": batch_id,
                    "attempt": attempt,
                    "custom_ids": [r.custom_id for r in chunk],
                    "collected": False,
                }
            )
        self._save(state)

    # --- main loop ---------------------------------------------------------------

    def advance(
        self, auth: Authorization, spent_usd: float, budget_usd: float, threshold_usd: float
    ) -> JobStatus:
        state = self._load()
        if state is None:
            pending = self.pending()
            if not pending:
                return "done"
            estimate = estimate_cost(pending, self.pricing, self.config)
            check_guards(self.client, estimate, auth, spent_usd, budget_usd, threshold_usd)
            created = self.now()
            state = _State(
                job_id=f"{created.strftime('%Y%m%dT%H%M%SZ')}-{self.prompt.sha256[:8]}",
                model=self.model,
                prompt_version=self.prompt.version,
                prompt_sha256=self.prompt.sha256,
                estimate=asdict(estimate),
            )
            self._submit(state, pending, attempt=1)
            return "submitted"

        if state.prompt_sha256 != self.prompt.sha256 or state.model != self.model:
            msg = (
                f"a batch job with another prompt or model is in progress ({self.state_path}). "
                "Let it finish or remove the state file on purpose."
            )
            raise DataPipelineError(msg)

        open_batches = [b for b in state.batches if not b["collected"]]
        if any(not self.client.batch_ended(b["id"]) for b in open_batches):
            return "waiting"
        for batch in open_batches:
            self._collect(state, batch)
        self._save(state)

        retry = [
            self.request(custom_id)
            for custom_id, failure in state.failures.items()
            if failure["attempt"] < MAX_ATTEMPTS and failure.get("retried") is not True
        ]
        if retry:
            estimate = estimate_cost(retry, self.pricing, self.config)
            check_guards(
                self.client, estimate, auth, spent_usd, budget_usd, threshold_usd, retry=True
            )
            for request in retry:
                state.failures[request.custom_id]["retried"] = True
            self._submit(state, retry, attempt=MAX_ATTEMPTS)
            return "submitted"
        return "done"

    def _collect(self, state: _State, batch: dict[str, Any]) -> None:
        records = []
        attempt = batch["attempt"]
        for result in self.client.batch_results(batch["id"]):
            records.append(self._record(state, result, attempt))
            if result.status != "succeeded":
                state.failures[result.custom_id] = _failure(attempt, result.status, result.error)
                continue
            try:
                parse_label(result.text, self.taxonomy)
            except LabelParseError as error:
                state.failures[result.custom_id] = _failure(attempt, "invalid", str(error))
                continue
            self.cache.put(self.request(result.custom_id), result)
            state.failures.pop(result.custom_id, None)
        self.cost_log.append(records)
        batch["collected"] = True

    def _record(self, state: _State, result: LLMResult, attempt: int) -> CallRecord:
        usage = result.usage or TokenUsage(0, 0)
        return CallRecord(
            experiment=f"silver_labels/{state.job_id}",
            backend=self.client.name,
            model=self.model,
            custom_id=result.custom_id,
            status=f"{result.status}/attempt{attempt}",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            # Offline backends cost nothing and must not count against the budget.
            cost_usd=self.pricing.cost_usd(self.model, usage, batch=True)
            if self.client.is_external
            else 0.0,
            batch=True,
            prompt_hash=self.prompt.sha256,
        )

    # --- outputs ---------------------------------------------------------------------

    def labels(self) -> list[dict[str, Any]]:
        """One row per item: the label, or the reason it is missing."""
        state = self._load()
        failures = state.failures if state else {}
        rows = []
        for item_id, item in self.items.items():
            cached = self.cache.get(self.request(item_id))
            row: dict[str, Any] = {
                "set": item.set,
                "item_id": item_id,
                "source_id": item.source_id,
                "topic": None,
                "urgency": None,
                "label_status": "missing",
                "backend": self.client.name,
                "model": self.model,
                "prompt_version": self.prompt.version,
                "prompt_sha256": self.prompt.sha256,
            }
            if cached is not None:
                label = parse_label(cached.text, self.taxonomy)
                row.update(topic=label.topic, urgency=label.urgency, label_status="valid")
            elif item_id in failures:
                row["label_status"] = failures[item_id]["status"]
            rows.append(row)
        return rows

    def job_summary(self) -> dict[str, Any]:
        state = self._load()
        if state is None:
            return {}
        experiment = f"silver_labels/{state.job_id}"
        records = [r for r in self.cost_log.records() if r["experiment"] == experiment]
        return {
            "job_id": state.job_id,
            "batches": [
                {"id": b["id"], "attempt": b["attempt"], "requests": len(b["custom_ids"])}
                for b in state.batches
            ],
            "estimate": state.estimate,
            "actual": {
                "requests": len(records),
                "input_tokens": sum(int(str(r["input_tokens"])) for r in records),
                "output_tokens": sum(int(str(r["output_tokens"])) for r in records),
                "cost_usd": round(sum(float(str(r["cost_usd"])) for r in records), 6),
            },
        }

    def archive_state(self) -> None:
        if self.state_path.exists():
            done = self.state_path.with_name(
                f"{self.state_path.stem}.done-{self.now().strftime('%Y%m%dT%H%M%SZ')}.json"
            )
            self.state_path.rename(done)


def write_silver_sets(
    con: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]], output_dir: Path
) -> dict[str, Path]:
    columns = [
        "set",
        "item_id",
        "source_id",
        "topic",
        "urgency",
        "label_status",
        "backend",
        "model",
        "prompt_version",
        "prompt_sha256",
    ]
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE silver_out ({', '.join(f'{c} VARCHAR' for c in columns)})"
    )
    if rows:
        con.executemany(
            f"INSERT INTO silver_out VALUES ({', '.join(['?'] * len(columns))})",
            [tuple(row[c] for c in columns) for row in rows],
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for set_name in SILVER_SETS:
        path = output_dir / f"{set_name}.parquet"
        con.execute(
            "COPY (SELECT * EXCLUDE (set) FROM silver_out "
            f"WHERE set = '{set_name}' ORDER BY item_id) "
            f"TO {sql.literal(path)} (FORMAT parquet, COMPRESSION zstd)"
        )
        paths[set_name] = path
    return paths
