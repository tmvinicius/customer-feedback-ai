"""LLM triage: runs on gold_dev, applies the C4/C5 rules and writes aggregates only."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import duckdb
import pytest

from customer_feedback_ai.data.manifest import read_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.sql import literal
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.evaluation.llm_triage import INVALID, topic_macro_f1, triage_request
from customer_feedback_ai.evaluation.metrics import macro_f1
from customer_feedback_ai.labeling.gold import GOLD_DEV, LabelStore, load_queue
from customer_feedback_ai.labeling.output import label_json_schema
from customer_feedback_ai.labeling.prompt import render_prompt
from customer_feedback_ai.labeling.silver import SilverItem, build_request
from customer_feedback_ai.labeling.taxonomy import Taxonomy, load_taxonomy
from customer_feedback_ai.llm.cache import request_key
from customer_feedback_ai.llm.cost_log import CostLog
from customer_feedback_ai.llm.local_config import load_local_llm_config
from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage
from customer_feedback_ai.pipelines import llm_triage

from .conftest import REPO_ROOT, SMALL_LABELING
from .test_gold import label_all

LOCAL = load_local_llm_config(REPO_ROOT / "configs" / "llm_local.yaml")
FIXED_NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


class FakeChat:
    """Local backend whose behaviour is set per model tag."""

    def __init__(
        self,
        truth: dict[str, tuple[str, str]],
        topics: tuple[str, ...],
        behaviour: dict[str, dict[str, Any]],
    ):
        self.truth, self.topics, self.behaviour = truth, topics, behaviour
        self.calls: list[tuple[str, str]] = []
        self.missing: set[str] = set()
        self._seen: dict[tuple[str, str], int] = {}

    @property
    def name(self) -> str:
        return "ollama-test"

    def chat(self, request: LLMRequest) -> LLMResult:
        key = (request.model, request.custom_id)
        self.calls.append(key)
        self._seen[key] = self._seen.get(key, 0) + 1
        b = self.behaviour.get(request.model, {})
        latency = b.get("latency", 1.0)
        if request.custom_id == "warm-up":
            return LLMResult("warm-up", "succeeded", text="{}", latency_s=9.9, load_s=2.0)
        if b.get("errored"):
            return LLMResult(request.custom_id, "errored", error="out of memory", latency_s=latency)
        if b.get("invalid_first") and self._seen[key] == 1:
            return LLMResult(request.custom_id, "succeeded", text="not json", latency_s=latency)
        topic, urgency = self.truth[request.custom_id]
        every = b.get("wrong_every", 0)
        digest = int(hashlib.sha256(request.custom_id.encode()).hexdigest()[:8], 16)
        if every and digest % every == 0:
            topic = self.topics[(self.topics.index(topic) + 1) % len(self.topics)]
        text = json.dumps({"topic": topic, "urgency": urgency})
        return LLMResult(
            request.custom_id,
            "succeeded",
            text=text,
            usage=TokenUsage(900, 12),
            latency_s=latency,
            load_s=0.1,
        )

    def missing_models(self, tags: Any) -> list[str]:
        return [tag for tag in tags if tag in self.missing]

    def model_details(self, tag: str) -> dict[str, Any]:
        return {"tag": tag, "quantization": "Q4_K_M", "parameter_size": "4B", "warning": None}

    def memory_snapshot(self, tag: str) -> dict[str, Any] | None:
        return {
            "tag": tag,
            "vram_share": self.behaviour.get(tag, {}).get("vram", 1.0),
            "size_bytes": 10,
        }


def make_client(
    paths: DataPaths, taxonomy: Taxonomy, behaviour: dict[str, dict[str, Any]]
) -> FakeChat:
    latest = LabelStore(paths.annotation_labels).latest()
    truth = {
        item.item_id: (
            latest[(item.item_id, "first")].topic,
            latest[(item.item_id, "first")].urgency,
        )
        for item in load_queue(paths.annotation_queue)
        if (item.item_id, "first") in latest
    }
    return FakeChat(truth, taxonomy.topic_ids, behaviour)


def triage(paths: DataPaths, taxonomy: Taxonomy, client: FakeChat, **kwargs: Any) -> dict[str, Any]:
    return llm_triage.run(
        paths, SMALL_LABELING, taxonomy, LOCAL, client, now=lambda: FIXED_NOW, **kwargs
    )


STANDARD: dict[str, dict[str, Any]] = {
    "gemma4:e4b": {"latency": 1.2},
    "qwen3.5:4b": {"latency": 0.8, "wrong_every": 2},
    "qwen3.5:9b": {"latency": 3.0, "errored": True},
    "llama3.1:8b": {"latency": 2.5, "vram": 0.7, "wrong_every": 5},
}


# --- inputs ------------------------------------------------------------------------


def test_needs_human_labels(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    with pytest.raises(DataPipelineError, match="no human labels"):
        triage(labeling_paths, taxonomy, FakeChat({}, taxonomy.topic_ids, {}))


def test_incomplete_gold_dev_is_refused_unless_it_is_a_trial(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    store = LabelStore(labeling_paths.annotation_labels)
    items = [i for i in load_queue(labeling_paths.annotation_queue) if i.set == GOLD_DEV][:10]
    for item in items:
        store.append(_label(item))
    client = make_client(labeling_paths, taxonomy, STANDARD)
    with pytest.raises(DataPipelineError, match="10 of 40"):
        triage(labeling_paths, taxonomy, client)

    report = triage(labeling_paths, taxonomy, client, allow_incomplete=True)
    assert report["valid_for_choice"] is False
    assert report["gold_dev_items"] == 10
    assert any("trial run" in note for note in report["notes"])


def test_missing_models_tell_how_to_pull_them(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    client = make_client(labeling_paths, taxonomy, STANDARD)
    client.missing = {"qwen3.5:9b"}
    with pytest.raises(DataPipelineError, match=r"ollama pull qwen3\.5:9b"):
        triage(labeling_paths, taxonomy, client)


# --- full run ----------------------------------------------------------------------


def test_triage_picks_c4_and_c5_and_writes_aggregates(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    client = make_client(labeling_paths, taxonomy, STANDARD)
    report = triage(labeling_paths, taxonomy, client)

    assert report["valid_for_choice"] is True
    assert report["decisions"]["c4"]["winner"] == "gemma4:e4b"
    assert "higher topic macro-F1" in report["decisions"]["c4"]["reason"]
    assert report["decisions"]["c5"]["winner"] == "llama3.1:8b"
    assert "qwen3.5:9b" in report["decisions"]["c5"]["reason"]
    assert report["suggested_chosen"] == {"c4": "gemma4:e4b", "c5": "llama3.1:8b"}

    gemma = report["candidates"]["gemma4:e4b"]
    assert gemma["topic_macro_f1"]["value"] == pytest.approx(1.0)
    assert gemma["valid_rate"] == 1.0
    assert gemma["latency_s"]["p50"] == pytest.approx(1.2)  # warm-up (9.9 s) left out
    assert gemma["latency_s"]["measured_calls"] == 40
    assert gemma["load_s"] == pytest.approx(2.0)
    assert gemma["quantization"] == "Q4_K_M"
    assert report["candidates"]["qwen3.5:9b"]["viable"] is False
    assert report["candidates"]["llama3.1:8b"]["vram_share"] == pytest.approx(0.7)


def test_outputs_have_no_complaint_text(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    triage(labeling_paths, taxonomy, make_client(labeling_paths, taxonomy, STANDARD))

    report_text = (labeling_paths.reports_dir / "llm_triage.json").read_text(encoding="utf-8")
    texts = [i.text for i in load_queue(labeling_paths.annotation_queue) if i.set == GOLD_DEV]
    assert not any(text in report_text for text in texts)

    path = llm_triage.predictions_path(labeling_paths, "gemma4:e4b")
    con = duckdb.connect()
    columns = [
        r[0]
        for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({literal(path)})").fetchall()
    ]
    assert columns == ["item_id", "topic", "urgency", "status", "attempts", "latency_s"]
    row = con.execute(f"SELECT count(*) FROM read_parquet({literal(path)})").fetchone()
    assert row == (40,)

    manifest = read_manifest(labeling_paths.manifest("llm_triage"))
    assert manifest.counts == {"gold_dev_items": 40, "candidates": 4}
    records = CostLog(labeling_paths.llm_cost_log).records()
    assert {r["model"] for r in records} == {
        "gemma4:e4b",
        "qwen3.5:4b",
        "qwen3.5:9b",
        "llama3.1:8b",
    }
    assert all(str(r["experiment"]).startswith("llm_triage/") for r in records)
    assert all("text" not in r for r in records)


def test_invalid_replies_are_retried_once(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    behaviour: dict[str, dict[str, Any]] = {
        **STANDARD,
        "gemma4:e4b": {"latency": 1.0, "invalid_first": True},
    }
    report = triage(labeling_paths, taxonomy, make_client(labeling_paths, taxonomy, behaviour))
    gemma = report["candidates"]["gemma4:e4b"]
    assert (gemma["retried"], gemma["valid_rate"]) == (40, 1.0)


def test_c4_tie_goes_to_the_faster_model(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    behaviour: dict[str, dict[str, Any]] = {
        **STANDARD,
        "gemma4:e4b": {"latency": 1.5, "wrong_every": 4},
        "qwen3.5:4b": {"latency": 0.7, "wrong_every": 4},
    }
    report = triage(labeling_paths, taxonomy, make_client(labeling_paths, taxonomy, behaviour))
    assert report["decisions"]["c4"]["winner"] == "qwen3.5:4b"
    assert report["decisions"]["c4"]["reason"].startswith("tie")


def test_a_failing_c4_candidate_is_disqualified(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    behaviour: dict[str, dict[str, Any]] = {**STANDARD, "gemma4:e4b": {"errored": True}}
    report = triage(labeling_paths, taxonomy, make_client(labeling_paths, taxonomy, behaviour))
    assert report["decisions"]["c4"]["winner"] == "qwen3.5:4b"
    assert "gemma4:e4b" in report["decisions"]["c4"]["reason"]


def test_rerun_reuses_cached_answers_unless_fresh(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    triage(
        labeling_paths,
        taxonomy,
        make_client(labeling_paths, taxonomy, STANDARD),
        models=["gemma4:e4b"],
    )

    cached = make_client(labeling_paths, taxonomy, STANDARD)
    report = triage(labeling_paths, taxonomy, cached, models=["gemma4:e4b"])
    assert report["candidates"]["gemma4:e4b"]["from_cache"] == 40
    assert cached.calls == [("gemma4:e4b", "warm-up")]
    assert report["valid_for_choice"] is False  # only one model

    fresh = make_client(labeling_paths, taxonomy, STANDARD)
    triage(labeling_paths, taxonomy, fresh, models=["gemma4:e4b"], use_cache=False)
    assert len(fresh.calls) == 41


# --- details -----------------------------------------------------------------------


def test_invalid_predictions_are_misses_not_a_class() -> None:
    truth = ["a", "a", "b", "b"]
    pred = ["a", INVALID, "b", "b"]
    # a: precision 1, recall 0.5, F1 2/3; b: F1 1. The invalid reply is a miss for "a".
    assert topic_macro_f1(truth, pred) == pytest.approx((2 / 3 + 1.0) / 2)
    # Counting "invalid" as a class would add an F1 of 0 and lower the average.
    assert macro_f1(truth, pred) == pytest.approx((2 / 3 + 1.0 + 0.0) / 3)


def test_triage_and_silver_share_the_cache_key(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    item = next(i for i in load_queue(labeling_paths.annotation_queue) if i.set == GOLD_DEV)
    prompt = render_prompt(SMALL_LABELING.silver.prompt, taxonomy)
    schema = label_json_schema(taxonomy)
    triage_key = request_key(
        triage_request(item.item_id, item.text, "gemma4:e4b", prompt, schema, SMALL_LABELING.silver)
    )
    silver = SilverItem("gold_dev_llm", item.item_id, item.source_id, item.text)
    silver_key = request_key(
        build_request(silver, prompt, schema, "gemma4:e4b", SMALL_LABELING.silver)
    )
    assert triage_key == silver_key


def _label(item: Any) -> Any:
    from .test_gold import label

    return label(item)
