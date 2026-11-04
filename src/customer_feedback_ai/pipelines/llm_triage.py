"""`make llm-triage`: run the four local LLM candidates on `gold_dev` and pick C4 and C5.

Needs the human `gold_dev` labels (G3) and the models pulled in Ollama. Writes
an aggregate report (`<DATA_DIR>/reports/llm_triage.json`), per-model
predictions without text (`<DATA_DIR>/gold/triage/`) and a manifest. Every call
goes to the call log, which later gives `make label-silver` its time estimate.

The pipeline only recommends: the maintainer records the choice in
docs/decisions.md and sets `chosen` in configs/llm_local.yaml.
"""

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.evaluation.llm_triage import (
    CandidateRun,
    GoldItem,
    decide,
    run_candidate,
    summarize,
)
from customer_feedback_ai.labeling.config import (
    LABELING_CONFIG_PATH,
    LabelingConfig,
    load_labeling_config,
)
from customer_feedback_ai.labeling.gold import GOLD_DEV, LabelStore, load_queue
from customer_feedback_ai.labeling.output import label_json_schema
from customer_feedback_ai.labeling.prompt import render_prompt
from customer_feedback_ai.labeling.taxonomy import TAXONOMY_PATH, Taxonomy, load_taxonomy
from customer_feedback_ai.llm.cache import ResultCache
from customer_feedback_ai.llm.client import ChatClient
from customer_feedback_ai.llm.cost_log import CallRecord, CostLog
from customer_feedback_ai.llm.local_config import (
    LOCAL_LLM_CONFIG_PATH,
    LocalLLMConfig,
    load_local_llm_config,
)
from customer_feedback_ai.llm.ollama_client import OllamaClient
from customer_feedback_ai.llm.types import LLMResult, TokenUsage
from customer_feedback_ai.pipelines._common import (
    LOGGER,
    default_paths,
    require,
    run_cli,
    write_json,
)


def gold_dev_items(paths: DataPaths, allow_incomplete: bool) -> tuple[list[GoldItem], int]:
    """`gold_dev` items with their first-round human labels, and the queue size."""
    queue = require(paths.annotation_queue, "Run `make annotate` first.")
    items = [item for item in load_queue(queue) if item.set == GOLD_DEV]
    latest = LabelStore(paths.annotation_labels).latest()
    labeled = [
        GoldItem(item.item_id, item.text, label.topic, label.urgency)
        for item in items
        if (label := latest.get((item.item_id, "first")))
    ]
    if not labeled:
        msg = "gold_dev has no human labels yet. Annotate it with `make annotate` (G3)."
        raise DataPipelineError(msg)
    if len(labeled) < len(items) and not allow_incomplete:
        msg = (
            f"gold_dev is incomplete: {len(labeled)} of {len(items)} items labeled. Finish the "
            "annotation, or pass --allow-incomplete for a trial run that is not valid "
            "for the choice."
        )
        raise DataPipelineError(msg)
    return labeled, len(items)


def write_predictions(
    con: duckdb.DuckDBPyConnection, run: CandidateRun, items: Sequence[GoldItem], path: Path
) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE triage_out (item_id VARCHAR, topic VARCHAR, urgency VARCHAR, "
        "status VARCHAR, attempts INTEGER, latency_s DOUBLE)"
    )
    latencies: list[float | None] = list(run.latencies) + [None] * (len(items) - len(run.latencies))
    rows = [
        (item.item_id, topic, urgency, status, attempts, latency)
        for item, topic, urgency, status, attempts, latency in zip(
            items, run.topics, run.urgencies, run.statuses, run.attempts, latencies, strict=True
        )
    ]
    con.executemany("INSERT INTO triage_out VALUES (?, ?, ?, ?, ?, ?)", rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY (SELECT * FROM triage_out ORDER BY item_id) TO {sql.literal(path)} "
        "(FORMAT parquet, COMPRESSION zstd)"
    )


def predictions_path(paths: DataPaths, tag: str) -> Path:
    return paths.triage_dir / f"{tag.replace(':', '_')}.parquet"


def run(
    paths: DataPaths,
    config: LabelingConfig,
    taxonomy: Taxonomy,
    local: LocalLLMConfig,
    client: ChatClient,
    *,
    models: Sequence[str] | None = None,
    allow_incomplete: bool = False,
    use_cache: bool = True,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    items, queue_size = gold_dev_items(paths, allow_incomplete)
    tags = (
        [local.check_candidate(tag) for tag in models]
        if models
        else [c.tag for c in local.candidates]
    )
    missing = client.missing_models(tags)
    if missing:
        pulls = " && ".join(f"ollama pull {tag}" for tag in missing)
        msg = f"models not available in Ollama: {missing}. Run: {pulls}"
        raise DataPipelineError(msg)

    prompt = render_prompt(config.silver.prompt, taxonomy)
    schema = label_json_schema(taxonomy)
    run_id = f"{now().strftime('%Y%m%dT%H%M%SZ')}-{prompt.sha256[:8]}"
    cost_log = CostLog(paths.llm_cost_log)
    cache = ResultCache(paths.llm_cache_dir / client.name) if use_cache else None
    slots = {c.tag: c.slot for c in local.candidates}
    criterion = config.silver_criterion
    con = connect(paths.tmp_dir)

    runs: list[CandidateRun] = []
    for tag in tags:
        LOGGER.info("triage: %s (%s) on %d gold_dev items", tag, slots[tag], len(items))

        def log_call(result: LLMResult, attempt: int, tag: str = tag) -> None:
            usage = result.usage or TokenUsage(0, 0)
            cost_log.append(
                [
                    CallRecord(
                        experiment=f"llm_triage/{run_id}",
                        backend=client.name,
                        model=tag,
                        custom_id=result.custom_id,
                        status=f"{result.status}/attempt{attempt}",
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                        cost_usd=0.0,
                        batch=False,
                        prompt_hash=prompt.sha256,
                        latency_s=result.latency_s,
                        load_s=result.load_s,
                    )
                ]
            )

        candidate = run_candidate(
            client,
            tag,
            slots[tag],
            items,
            prompt,
            taxonomy,
            schema,
            config.silver,
            cache=cache,
            log_call=log_call,
        )
        write_predictions(con, candidate, items, predictions_path(paths, tag))
        runs.append(candidate)

    summaries = {
        r.tag: summarize(r, items, criterion.bootstrap_resamples, criterion.seed) for r in runs
    }
    decisions = decide(runs, items, criterion.bootstrap_resamples, criterion.seed)
    notes = []
    if len(items) < queue_size:
        notes.append(
            f"trial run on {len(items)} of {queue_size} gold_dev items: "
            "not valid for choosing C4 and C5"
        )
    if len(items) < 200:
        notes.append(
            "latency comes from fewer than 200 calls; the final latency measurement (M3 step 9) "
            "uses at least 200 complaints"
        )
    if any(summary["from_cache"] for summary in summaries.values()):
        notes.append(
            "some answers came from the cache with their original latency; "
            "use --fresh to re-measure"
        )
    report = {
        "run_id": run_id,
        "valid_for_choice": len(items) == queue_size and set(tags) == set(slots),
        "gold_dev_items": len(items),
        "prompt": {"version": prompt.version, "sha256": prompt.sha256},
        "decoding": local.decoding.model_dump(mode="json"),
        "candidates": summaries,
        "decisions": decisions,
        "suggested_chosen": {slot: d["winner"] for slot, d in decisions.items()},
        "notes": notes,
    }
    report_path = paths.reports_dir / "llm_triage.json"
    write_json(report, report_path)

    labels = paths.annotation_labels
    write_manifest(
        build_manifest(
            stage="llm_triage",
            config={
                "local_llm": local.model_dump(mode="json"),
                "prompt_version": prompt.version,
                "prompt_sha256": prompt.sha256,
                "models": tags,
                "use_cache": use_cache,
            },
            seed=local.decoding.seed,
            inputs=[file_record(paths.annotation_queue, paths.relative(paths.annotation_queue))]
            + ([file_record(labels, paths.relative(labels))] if labels.exists() else []),
            outputs=[file_record(report_path, paths.relative(report_path))]
            + [
                file_record(
                    predictions_path(paths, r.tag), paths.relative(predictions_path(paths, r.tag))
                )
                for r in runs
            ],
            counts={"gold_dev_items": len(items), "candidates": len(runs)},
            details={"decisions": decisions},
        ),
        paths.manifest("llm_triage"),
    )
    for slot, decision in decisions.items():
        LOGGER.info("%s: %s (%s)", slot.upper(), decision["winner"], decision["reason"])
    for note in notes:
        LOGGER.warning("%s", note)
    LOGGER.info(
        "record the choice in docs/decisions.md, then set chosen.c4/chosen.c5 "
        "in configs/llm_local.yaml"
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", help="subset of candidate tags (default: all four)")
    parser.add_argument(
        "--allow-incomplete", action="store_true", help="trial run, not valid for the choice"
    )
    parser.add_argument(
        "--fresh", action="store_true", help="ignore cached answers and re-measure latency"
    )
    parser.add_argument("--config", type=Path, default=LABELING_CONFIG_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument("--local-config", type=Path, default=LOCAL_LLM_CONFIG_PATH)
    args = parser.parse_args(argv)

    def step() -> dict[str, Any]:
        local = load_local_llm_config(args.local_config)
        return run(
            default_paths(),
            load_labeling_config(args.config),
            load_taxonomy(args.taxonomy),
            local,
            OllamaClient(local),
            models=args.models,
            allow_incomplete=args.allow_incomplete,
            use_cache=not args.fresh,
        )

    run_cli(step)


if __name__ == "__main__":
    main()
