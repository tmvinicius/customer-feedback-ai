"""LLM triage: run each local candidate on `gold_dev` and pick C4 and C5.

Rules (docs/decisions.md, 2026-11-04):
- every candidate gets the same prompt, schema, decoding and machine;
- each complaint is one individual call, after a warm-up call that loads the
  model and is left out of the measurements;
- an invalid reply is retried once; if it is still invalid, the prediction
  counts as an error (it never becomes a class of its own);
- a candidate is viable when no call fails at runtime (server errors such as
  running out of memory). Layers on the CPU are allowed; the VRAM share is
  recorded;
- C4: higher topic macro-F1, tie (paired 95% interval containing zero) broken
  by p50 latency; a non-viable C4 candidate is disqualified;
- C5: higher topic macro-F1 among viable candidates; cut when none is viable.

Only labels, timings and aggregates are produced: no complaint text.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from customer_feedback_ai.evaluation.bootstrap import bootstrap_interval, quantile
from customer_feedback_ai.evaluation.metrics import macro_f1, recall_of
from customer_feedback_ai.evaluation.triage import (
    Candidate,
    TriageDecision,
    choose_larger,
    choose_smaller,
)
from customer_feedback_ai.labeling.config import SilverConfig
from customer_feedback_ai.labeling.output import LabelParseError, parse_label
from customer_feedback_ai.labeling.prompt import ClassificationPrompt
from customer_feedback_ai.labeling.taxonomy import URGENCY_LEVELS, Taxonomy
from customer_feedback_ai.llm.cache import ResultCache
from customer_feedback_ai.llm.client import ChatClient
from customer_feedback_ai.llm.types import LLMRequest, LLMResult

INVALID = "__invalid__"
MAX_ATTEMPTS = 2
# Synthetic text for the warm-up call: it only loads the model.
WARM_UP_TEXT = (
    "Pedi o cancelamento do plano e continuo sendo cobrado. Texto sintético de aquecimento."
)

CallLogger = Callable[[LLMResult, int], None]


@dataclass(frozen=True)
class GoldItem:
    item_id: str
    text: str
    topic: str
    urgency: str


@dataclass
class CandidateRun:
    tag: str
    slot: str
    topics: list[str] = field(default_factory=list)
    urgencies: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    attempts: list[int] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    errored: int = 0
    invalid: int = 0
    retried: int = 0
    from_cache: int = 0
    wall_seconds: float = 0.0
    load_s: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] | None = None

    @property
    def viable(self) -> bool:
        return self.errored == 0

    @property
    def latency_p50_s(self) -> float:
        return quantile(sorted(self.latencies), 0.5) if self.latencies else float("inf")


def without_invalid(metric_labels: Sequence[str], predictions: Sequence[str]) -> list[str]:
    return sorted((set(metric_labels) | set(predictions)) - {INVALID})


def topic_macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float | None:
    """Macro-F1 where an invalid reply is a miss, never an extra class."""
    return macro_f1(y_true, y_pred, labels=without_invalid(y_true, y_pred))


def urgency_macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float | None:
    return macro_f1(y_true, y_pred, labels=list(URGENCY_LEVELS))


def triage_request(
    item_id: str,
    text: str,
    tag: str,
    prompt: ClassificationPrompt,
    schema: dict[str, Any],
    config: SilverConfig,
) -> LLMRequest:
    """Same request as the silver job, so its answers can be reused from the cache."""
    return LLMRequest(
        custom_id=item_id,
        model=tag,
        system=prompt.system,
        user=prompt.user_message(text),
        max_tokens=config.max_tokens,
        effort=config.effort,
        json_schema=schema,
        cache_system=config.cache_system_prompt,
    )


def run_candidate(
    client: ChatClient,
    tag: str,
    slot: str,
    items: Sequence[GoldItem],
    prompt: ClassificationPrompt,
    taxonomy: Taxonomy,
    schema: dict[str, Any],
    config: SilverConfig,
    *,
    cache: ResultCache | None = None,
    log_call: CallLogger | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> CandidateRun:
    run = CandidateRun(tag=tag, slot=slot, details=client.model_details(tag))
    warm_up = client.chat(triage_request("warm-up", WARM_UP_TEXT, tag, prompt, schema, config))
    run.load_s = warm_up.load_s

    start = clock()
    for item in items:
        request = triage_request(item.item_id, item.text, tag, prompt, schema, config)
        topic, urgency, status, attempts = INVALID, INVALID, "invalid", 0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            cached = cache.get(request) if cache is not None and attempt == 1 else None
            result = cached or client.chat(request)
            attempts = attempt
            if cached is not None:
                run.from_cache += 1
            elif log_call is not None:
                log_call(result, attempt)
            if attempt == 1 and result.latency_s is not None:
                run.latencies.append(result.latency_s)
            if result.status == "errored":
                status = "errored"
                break
            try:
                label = parse_label(result.text, taxonomy) if result.status == "succeeded" else None
            except LabelParseError:
                label = None
            if label is not None:
                topic, urgency, status = label.topic, label.urgency, "valid"
                if cache is not None and cached is None:
                    cache.put(request, result)
                break
            if attempt < MAX_ATTEMPTS:
                run.retried += 1
        run.errored += status == "errored"
        run.invalid += status == "invalid"
        run.topics.append(topic)
        run.urgencies.append(urgency)
        run.statuses.append(status)
        run.attempts.append(attempts)
    run.wall_seconds = clock() - start
    run.memory = client.memory_snapshot(tag)
    return run


def _interval(
    metric: Callable[[Sequence[str], Sequence[str]], float | None],
    truth: Sequence[str],
    pred: Sequence[str],
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    interval = bootstrap_interval(metric, truth, pred, resamples=resamples, seed=seed)
    return {"value": interval.point, "ci_low": interval.low, "ci_high": interval.high}


def summarize(
    run: CandidateRun, items: Sequence[GoldItem], resamples: int, seed: int
) -> dict[str, Any]:
    gold_topics = [item.topic for item in items]
    gold_urgency = [item.urgency for item in items]
    latencies = sorted(run.latencies)
    n = len(items)
    memory = run.memory or {}
    return {
        "tag": run.tag,
        "slot": run.slot,
        "n": n,
        "viable": run.viable,
        "topic_macro_f1": _interval(topic_macro_f1, gold_topics, run.topics, resamples, seed),
        "urgency_macro_f1": _interval(
            urgency_macro_f1, gold_urgency, run.urgencies, resamples, seed
        ),
        "high_urgency_recall": {
            "value": recall_of(gold_urgency, run.urgencies, "alta"),
            "support": gold_urgency.count("alta"),
        },
        "valid_rate": (n - run.invalid - run.errored) / n if n else None,
        "invalid": run.invalid,
        "errored": run.errored,
        "retried": run.retried,
        "from_cache": run.from_cache,
        "latency_s": {
            "p50": quantile(latencies, 0.5) if latencies else None,
            "p95": quantile(latencies, 0.95) if latencies else None,
            "measured_calls": len(latencies),
        },
        "throughput_items_per_s": n / run.wall_seconds if run.wall_seconds > 0 else None,
        "wall_seconds": run.wall_seconds,
        "load_s": run.load_s,
        "quantization": run.details.get("quantization"),
        "parameter_size": run.details.get("parameter_size"),
        "quantization_warning": run.details.get("warning"),
        "vram_share": memory.get("vram_share"),
        "size_bytes": memory.get("size_bytes"),
    }


def _candidate(run: CandidateRun) -> Candidate:
    return Candidate(
        name=run.tag,
        topic_predictions=tuple(run.topics),
        latency_p50_s=run.latency_p50_s,
        viable=run.viable,
        vram_share=(run.memory or {}).get("vram_share"),
    )


def _decision_dict(decision: TriageDecision) -> dict[str, Any]:
    difference = decision.difference
    return {
        "slot": decision.slot,
        "winner": decision.winner,
        "reason": decision.reason,
        "topic_macro_f1": decision.macro_f1,
        "difference": None
        if difference is None
        else {"value": difference.point, "ci_low": difference.low, "ci_high": difference.high},
    }


def decide(
    runs: Sequence[CandidateRun], items: Sequence[GoldItem], resamples: int, seed: int
) -> dict[str, Any]:
    """Apply the C4 and C5 rules to the runs of each slot."""
    gold_topics = [item.topic for item in items]
    decisions: dict[str, Any] = {}
    c4 = [run for run in runs if run.slot == "c4"]
    viable_c4 = [run for run in c4 if run.viable]
    if len(viable_c4) == 2:
        decision = choose_smaller(
            gold_topics,
            _candidate(viable_c4[0]),
            _candidate(viable_c4[1]),
            resamples=resamples,
            seed=seed,
            metric=topic_macro_f1,
        )
        decisions["c4"] = _decision_dict(decision)
    elif c4:
        winner = viable_c4[0].tag if viable_c4 else None
        dropped = sorted(run.tag for run in c4 if not run.viable)
        reason = (
            f"only viable C4 candidate; dropped as not viable: {dropped}"
            if winner
            else "no viable C4 candidate"
        )
        decisions["c4"] = {
            "slot": "C4",
            "winner": winner,
            "reason": reason,
            "topic_macro_f1": {run.tag: topic_macro_f1(gold_topics, run.topics) for run in c4},
            "difference": None,
        }
    c5 = [run for run in runs if run.slot == "c5"]
    if c5:
        decisions["c5"] = _decision_dict(
            choose_larger(gold_topics, [_candidate(run) for run in c5], metric=topic_macro_f1)
        )
    return decisions
