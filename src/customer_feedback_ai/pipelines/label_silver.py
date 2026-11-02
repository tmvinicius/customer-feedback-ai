"""`make label-silver`: silver labels with the LLM in batch.

Each run moves the job forward: estimate and submit, or collect and retry, or
write the labels. Without `--wait` it returns right after submitting; run it
again later to collect. `--llm fake` runs offline with `FakeLLM`, for synthetic
data and tests; its labels are not real labels.

Paid runs need CONFIRM_COST=1, ALLOW_EXTERNAL_LLM=true (G1) and, above the
approval threshold, APPROVED_USD (G4). See `labeling/silver.py`.
"""

import argparse
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from customer_feedback_ai.data.config import DATA_CONFIG_PATH, DuckDBConfig, load_data_config
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.labeling.config import (
    LABELING_CONFIG_PATH,
    LabelingConfig,
    load_labeling_config,
)
from customer_feedback_ai.labeling.gold import load_queue
from customer_feedback_ai.labeling.output import label_json_schema
from customer_feedback_ai.labeling.prompt import render_prompt
from customer_feedback_ai.labeling.silver import (
    Authorization,
    SilverJob,
    select_items,
    write_silver_sets,
)
from customer_feedback_ai.labeling.taxonomy import TAXONOMY_PATH, Taxonomy, load_taxonomy
from customer_feedback_ai.llm.anthropic_client import AnthropicBatchClient
from customer_feedback_ai.llm.client import BatchLLMClient
from customer_feedback_ai.llm.cost_log import CostLog
from customer_feedback_ai.llm.fake import FakeLLM
from customer_feedback_ai.llm.pricing import PRICING_PATH, Pricing, load_pricing
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, require, run_cli
from customer_feedback_ai.settings import Settings, get_settings

Outcome = Literal["submitted", "waiting", "done"]


def make_client(kind: str, settings: Settings) -> BatchLLMClient:
    if kind == "fake":
        return FakeLLM()
    key = settings.anthropic_api_key
    return AnthropicBatchClient(api_key=key.get_secret_value() if key else None)


def run(
    paths: DataPaths,
    config: LabelingConfig,
    taxonomy: Taxonomy,
    pricing: Pricing,
    settings: Settings,
    client: BatchLLMClient,
    auth: Authorization,
    *,
    wait: bool = False,
    poll_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    duckdb_config: DuckDBConfig | None = None,
) -> Outcome:
    queue = require(paths.annotation_queue, "Run `make annotate` once to build the gold queue.")
    silver = config.silver
    model = settings.llm_model_cheap if silver.model_role == "cheap" else settings.llm_model_premium
    prompt = render_prompt(silver.prompt, taxonomy)
    con = connect(paths.tmp_dir, duckdb_config)
    items = select_items(con, paths.splits_dir("silver"), load_queue(queue), silver)
    cost_log = CostLog(paths.llm_cost_log)
    job = SilverJob(
        items=items,
        prompt=prompt,
        taxonomy=taxonomy,
        schema=label_json_schema(taxonomy),
        model=model,
        config=silver,
        client=client,
        pricing=pricing,
        cache_dir=paths.llm_cache_dir,
        cost_log=cost_log,
        state_path=paths.silver_state,
    )

    while True:
        status = job.advance(
            auth,
            spent_usd=cost_log.spent_usd(),
            budget_usd=settings.llm_budget_usd,
            threshold_usd=settings.llm_job_approval_threshold_usd,
        )
        if status == "done":
            break
        if not wait:
            LOGGER.info("batch job %s; run again to collect the results", status)
            return status
        if status == "waiting":
            sleep(poll_seconds)

    rows = job.labels()
    outputs = write_silver_sets(con, rows, paths.silver_labels_dir)
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['set']}_{row['label_status']}"
        counts[key] = counts.get(key, 0) + 1
    write_manifest(
        build_manifest(
            stage="silver_labels",
            config={
                **silver.model_dump(mode="json"),
                "backend": client.name,
                "model": model,
                "prompt_version": prompt.version,
                "prompt_sha256": prompt.sha256,
                "pricing_checked_at": pricing.checked_at.isoformat(),
            },
            seed=silver.seed,
            inputs=[file_record(queue, paths.relative(queue))],
            outputs=[file_record(path, paths.relative(path)) for path in outputs.values()],
            counts=counts,
            details={"job": job.job_summary()},
        ),
        paths.manifest("silver_labels"),
    )
    job.archive_state()
    LOGGER.info("silver labels written: %s", counts)
    return "done"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=["anthropic", "fake"], default="anthropic")
    parser.add_argument("--wait", action="store_true", help="poll until the job is done")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--approved-usd", type=float, default=None, help="G4 approved amount")
    parser.add_argument("--config", type=Path, default=LABELING_CONFIG_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument("--pricing", type=Path, default=PRICING_PATH)
    parser.add_argument("--data-config", type=Path, default=DATA_CONFIG_PATH)
    args = parser.parse_args(argv)
    settings = get_settings()
    auth = Authorization(
        allow_external=settings.allow_external_llm,
        confirm_cost=os.environ.get("CONFIRM_COST") == "1",
        approved_usd=args.approved_usd,
    )
    run_cli(
        lambda: run(
            default_paths(),
            load_labeling_config(args.config),
            load_taxonomy(args.taxonomy),
            load_pricing(args.pricing),
            settings,
            make_client(args.llm, settings),
            auth,
            wait=args.wait or args.llm == "fake",
            poll_seconds=args.poll_seconds,
            duckdb_config=load_data_config(args.data_config).duckdb,
        )
    )


if __name__ == "__main__":
    main()
