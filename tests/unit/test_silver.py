"""Silver job: item selection, cost estimate, guards, retries, cache and outputs. No network."""

from datetime import date
from typing import Any

import duckdb
import pytest

from customer_feedback_ai.data.manifest import read_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.sql import literal
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.gold import GOLD_DEV, LabelStore, load_queue
from customer_feedback_ai.labeling.output import label_json_schema
from customer_feedback_ai.labeling.prompt import render_prompt
from customer_feedback_ai.labeling.silver import (
    GOLD_DEV_LLM,
    SILVER_TRAIN,
    SILVER_VAL,
    Authorization,
    CostEstimate,
    CostGuardError,
    build_request,
    check_guards,
    estimate_cost,
    select_items,
)
from customer_feedback_ai.labeling.taxonomy import Taxonomy, load_taxonomy
from customer_feedback_ai.llm.cost_log import CostLog
from customer_feedback_ai.llm.fake import FakeLLM
from customer_feedback_ai.llm.pricing import ModelPrices, Pricing
from customer_feedback_ai.llm.types import LLMRequest, LLMResult
from customer_feedback_ai.pipelines import gold_report as gold_report_pipeline
from customer_feedback_ai.pipelines import label_silver
from customer_feedback_ai.settings import Settings

from .conftest import REPO_ROOT, SMALL_LABELING
from .test_gold import label_all

PRICING = Pricing(
    checked_at=date(2026, 11, 11),
    source="test",
    batch_discount=0.5,
    models={
        "claude-haiku-5-5": ModelPrices(
            max_prompt_tokens=100_000,
            input=0.10,
            output=0.50,
            cache_write_5m=0.125,
            cache_read=0.01,
        )
    },
)
FULL = Authorization(allow_external=True, confirm_cost=True)


class ExternalFake(FakeLLM):
    """Behaves like a paid external backend, without leaving the machine."""

    @property
    def name(self) -> str:
        return "external-test"

    @property
    def is_external(self) -> bool:
        return True


class RefusingFake(FakeLLM):
    def _answer(self, request: LLMRequest) -> LLMResult:
        return LLMResult(request.custom_id, "refused", error="refusal")


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def run(
    paths: DataPaths, taxonomy: Taxonomy, client: FakeLLM, auth: Authorization = FULL, **kwargs: Any
) -> str:
    return label_silver.run(
        paths,
        SMALL_LABELING,
        taxonomy,
        PRICING,
        kwargs.pop("cfg", settings()),
        client,
        auth,
        wait=kwargs.pop("wait", True),
        sleep=lambda _: None,
        **kwargs,
    )


def read(paths: DataPaths, set_name: str) -> list[tuple[Any, ...]]:
    path = paths.silver_labels_dir / f"{set_name}.parquet"
    return (
        duckdb.connect()
        .execute(
            "SELECT item_id, topic, urgency, label_status, backend "
            f"FROM read_parquet({literal(path)})"
        )
        .fetchall()
    )


# --- selection and estimate -------------------------------------------------------


def test_items_come_from_the_right_windows(labeling_paths: DataPaths) -> None:
    queue = load_queue(labeling_paths.annotation_queue)
    items = select_items(
        duckdb.connect(), labeling_paths.splits_dir("silver"), queue, SMALL_LABELING.silver
    )
    by_set: dict[str, set[str]] = {}
    for item in items:
        by_set.setdefault(item.set, set()).add(item.item_id)
    gold_dev = {i.item_id for i in queue if i.set == GOLD_DEV}

    assert len(by_set[SILVER_TRAIN]) == 200
    assert len(by_set[SILVER_VAL]) == 50
    assert by_set[GOLD_DEV_LLM] == gold_dev
    assert not by_set[SILVER_VAL] & gold_dev
    assert not by_set[SILVER_TRAIN] & by_set[SILVER_VAL]


def test_silver_needs_the_gold_queue(labeling_paths: DataPaths) -> None:
    with pytest.raises(DataPipelineError, match="no gold_dev items"):
        select_items(
            duckdb.connect(), labeling_paths.splits_dir("silver"), [], SMALL_LABELING.silver
        )


def test_estimate_follows_the_heuristic(taxonomy: Taxonomy) -> None:
    request = LLMRequest("a", "claude-haiku-5-5", "s" * 70, "u" * 280, max_tokens=10)
    estimate = estimate_cost([request, request], PRICING, SMALL_LABELING.silver)
    assert estimate.input_tokens == 2 * 100
    assert estimate.output_tokens == 2 * 200
    assert estimate.cost_usd == pytest.approx(2 * (100 * 0.10 + 200 * 0.50) / 1e6 * 0.5)


# --- guards ------------------------------------------------------------------------


def estimate(cost: float) -> CostEstimate:
    return CostEstimate("claude-haiku-5-5", 10, 1000, 100, cost)


def test_offline_backend_needs_no_authorization() -> None:
    check_guards(FakeLLM(), estimate(100.0), Authorization(), 0.0, 30.0, 5.0)


@pytest.mark.parametrize(
    ("auth", "cost", "spent", "message"),
    [
        (Authorization(confirm_cost=True), 1.0, 0.0, "G1"),
        (Authorization(allow_external=True), 1.0, 0.0, "CONFIRM_COST=1"),
        (FULL, 1.0, 29.5, "exceed LLM_BUDGET_USD"),
        (FULL, 6.0, 0.0, "APPROVED_USD"),
        (Authorization(True, True, approved_usd=5.5), 6.0, 0.0, "APPROVED_USD"),
    ],
)
def test_paid_runs_are_blocked_until_authorized(
    auth: Authorization, cost: float, spent: float, message: str
) -> None:
    with pytest.raises(CostGuardError, match=message):
        check_guards(ExternalFake(), estimate(cost), auth, spent, 30.0, 5.0)


def test_approved_amount_unlocks_a_large_job() -> None:
    check_guards(ExternalFake(), estimate(6.0), Authorization(True, True, 6.5), 0.0, 30.0, 5.0)


# --- job ---------------------------------------------------------------------------


def test_offline_job_labels_everything_and_retries_invalid_replies(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    client = FakeLLM(invalid_first_every=4)
    assert run(labeling_paths, taxonomy, client, Authorization()) == "done"

    attempts = [b for b in client.batches.values()]
    assert len(attempts) > 3  # 290 requests in chunks of 100, plus one retry batch
    rows = (
        read(labeling_paths, SILVER_TRAIN)
        + read(labeling_paths, SILVER_VAL)
        + read(labeling_paths, GOLD_DEV_LLM)
    )
    assert len(rows) == 290
    assert {r[3] for r in rows} == {"valid"}
    assert {r[4] for r in rows} == {"fake"}
    assert all(r[1] in taxonomy.topic_ids and r[2] in taxonomy.urgency_ids for r in rows)

    manifest = read_manifest(labeling_paths.manifest("silver_labels"))
    assert manifest.counts == {
        "silver_train_valid": 200,
        "silver_val_valid": 50,
        "gold_dev_llm_valid": 40,
    }
    assert manifest.config["backend"] == "fake"
    assert manifest.details["job"] == {} or manifest.details["job"]["actual"]["cost_usd"] == 0
    log = CostLog(labeling_paths.llm_cost_log)
    assert log.spent_usd() == 0
    assert {r["backend"] for r in log.records()} == {"fake"}
    assert not labeling_paths.silver_state.exists()


def test_rerun_uses_the_cache(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    run(labeling_paths, taxonomy, FakeLLM(), Authorization())
    again = FakeLLM()
    assert run(labeling_paths, taxonomy, again, Authorization()) == "done"
    assert again.batches == {}


def test_offline_labels_never_count_as_real_ones(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    run(labeling_paths, taxonomy, FakeLLM(), Authorization())
    with pytest.raises(CostGuardError, match="G1"):
        run(labeling_paths, taxonomy, ExternalFake(), Authorization())


def test_paid_job_records_estimate_and_actual_cost(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    client = ExternalFake()
    assert run(labeling_paths, taxonomy, client, wait=False) == "submitted"
    assert labeling_paths.silver_state.exists()
    assert run(labeling_paths, taxonomy, client, wait=False) == "done"

    job = read_manifest(labeling_paths.manifest("silver_labels")).details["job"]
    assert job["estimate"]["requests"] == 290
    assert job["estimate"]["cost_usd"] > 0
    assert job["actual"]["requests"] == 290
    # The manifest rounds to six decimal places.
    assert job["actual"]["cost_usd"] == pytest.approx(
        CostLog(labeling_paths.llm_cost_log).spent_usd(), abs=1e-6
    )
    assert job["actual"]["cost_usd"] > 0


def test_budget_blocks_a_paid_job(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    tiny = settings(llm_budget_usd=0.0001, llm_job_approval_threshold_usd=0.0001)
    with pytest.raises(CostGuardError, match="LLM_BUDGET_USD"):
        run(labeling_paths, taxonomy, ExternalFake(), cfg=tiny)
    assert not labeling_paths.silver_state.exists()


def test_refusals_are_retried_once_then_recorded(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    client = RefusingFake()
    assert run(labeling_paths, taxonomy, client, Authorization()) == "done"
    assert len(client.batches) == 6  # three chunks, then three retry chunks
    assert {r[3] for r in read(labeling_paths, SILVER_TRAIN)} == {"refused"}


def test_a_running_job_with_another_prompt_is_not_mixed(
    labeling_paths: DataPaths, taxonomy: Taxonomy, tmp_path: Any
) -> None:
    client = ExternalFake()
    run(labeling_paths, taxonomy, client, wait=False)
    changed = tmp_path / "v2.md"
    changed.write_text(
        SMALL_LABELING.silver.prompt.read_text(encoding="utf-8") + "\nNova regra.\n",
        encoding="utf-8",
    )
    config = SMALL_LABELING.model_copy(
        update={"silver": SMALL_LABELING.silver.model_copy(update={"prompt": changed})}
    )
    with pytest.raises(DataPipelineError, match="another prompt or model"):
        label_silver.run(
            labeling_paths,
            config,
            taxonomy,
            PRICING,
            settings(),
            client,
            FULL,
            wait=False,
            sleep=lambda _: None,
        )


def test_report_measures_llm_against_gold_dev(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    run(labeling_paths, taxonomy, FakeLLM(), Authorization())
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    report = gold_report_pipeline.run(labeling_paths, SMALL_LABELING, taxonomy)

    comparison = report["silver_vs_gold_dev"]
    assert comparison["backends"] == ["fake"]
    assert comparison["topic"]["n"] == 40
    assert comparison["urgency"]["n"] == 40


def test_request_carries_prompt_schema_and_cache_flag(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    queue = load_queue(labeling_paths.annotation_queue)
    item = select_items(
        duckdb.connect(), labeling_paths.splits_dir("silver"), queue, SMALL_LABELING.silver
    )[0]
    prompt = render_prompt(SMALL_LABELING.silver.prompt, taxonomy)
    request = build_request(
        item, prompt, label_json_schema(taxonomy), "claude-haiku-5-5", SMALL_LABELING.silver
    )

    assert request.custom_id == item.item_id
    assert request.system == prompt.system
    assert item.text in request.user
    assert request.json_schema == label_json_schema(taxonomy)
    assert request.cache_system is True
    assert LabelStore(labeling_paths.annotation_labels).all() == []
