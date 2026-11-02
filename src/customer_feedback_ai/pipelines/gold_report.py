"""`make gold-report`: export the gold sets and report coverage, kappa and alerts.

When the silver job has labeled the `gold_dev` items, the report also measures
the agreement between the LLM and the human labels (AGENTS.md, section 7).
"""

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.labeling.agreement import agreement
from customer_feedback_ai.labeling.config import (
    LABELING_CONFIG_PATH,
    LabelingConfig,
    load_labeling_config,
)
from customer_feedback_ai.labeling.gold import (
    GOLD_DEV,
    GOLD_SETS,
    LabelStore,
    export_gold,
    gold_report,
    load_queue,
)
from customer_feedback_ai.labeling.silver import GOLD_DEV_LLM
from customer_feedback_ai.labeling.taxonomy import TAXONOMY_PATH, Taxonomy, load_taxonomy
from customer_feedback_ai.pipelines._common import (
    LOGGER,
    default_paths,
    require,
    run_cli,
    write_json,
)


def silver_vs_gold(con: duckdb.DuckDBPyConnection, gold_dev: Path, silver: Path) -> dict[str, Any]:
    backends = con.execute(
        f"SELECT DISTINCT backend FROM read_parquet({sql.literal(silver)}) ORDER BY 1"
    ).fetchall()
    rows = con.execute(
        f"SELECT g.topic, s.topic, g.urgency, s.urgency "
        f"FROM read_parquet({sql.literal(gold_dev)}) AS g "
        f"JOIN read_parquet({sql.literal(silver)}) AS s USING (item_id) "
        "WHERE s.label_status = 'valid' ORDER BY item_id"
    ).fetchall()
    # Labels from the offline FakeLLM measure nothing; the backend says which ran.
    result: dict[str, Any] = {"backends": [str(b[0]) for b in backends]}
    for name, first, second in (("topic", 0, 1), ("urgency", 2, 3)):
        stats = agreement([str(r[first]) for r in rows], [str(r[second]) for r in rows])
        result[name] = {"n": stats.n, "observed": stats.observed, "kappa": stats.kappa}
    return result


def run(paths: DataPaths, config: LabelingConfig, taxonomy: Taxonomy) -> dict[str, Any]:
    queue = require(paths.annotation_queue, "Run `make annotate` first.")
    items = load_queue(queue)
    latest = LabelStore(paths.annotation_labels).latest()
    con = connect(paths.tmp_dir)
    outputs = {gold_set: paths.gold_set(gold_set) for gold_set in GOLD_SETS}
    counts = export_gold(con, items, latest, outputs)

    report = gold_report(items, latest, config.gold, taxonomy)
    report["generated_on"] = date.today().isoformat()
    silver = paths.silver_labels_dir / f"{GOLD_DEV_LLM}.parquet"
    if silver.exists():
        report["silver_vs_gold_dev"] = silver_vs_gold(con, outputs[GOLD_DEV], silver)
    write_json(report, paths.gold_report)

    labels = paths.annotation_labels
    inputs = [file_record(queue, paths.relative(queue))]
    if labels.exists():
        inputs.append(file_record(labels, paths.relative(labels)))
    write_manifest(
        build_manifest(
            stage="gold_sets",
            config=config.gold.model_dump(mode="json"),
            inputs=inputs,
            outputs=[
                file_record(path, paths.relative(path), rows=counts[name])
                for name, path in outputs.items()
            ],
            counts={f"labeled_{name}": n for name, n in counts.items()},
        ),
        paths.manifest("gold_sets"),
    )
    for name in GOLD_SETS:
        info = report["sets"][name]
        LOGGER.info("%s: %d of %d labeled", name, info["labeled"], info["items"])
    for alert in report["alerts"]:
        LOGGER.warning("%s", alert)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=LABELING_CONFIG_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    args = parser.parse_args(argv)
    run_cli(
        lambda: run(
            default_paths(), load_labeling_config(args.config), load_taxonomy(args.taxonomy)
        )
    )


if __name__ == "__main__":
    main()
