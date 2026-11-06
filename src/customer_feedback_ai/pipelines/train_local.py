"""`make train-local`: train and measure the local models on the silver labels.

Models: B0 (majority class), B1 (keyword rules), C1 (TF-IDF + logistic
regression), C2 (Serafim embeddings + logistic regression) and C3 (BERTimbau
fine-tuned with two heads). C2 and C3 need the optional PyTorch dependencies
(`make setup DEEP=1`).

Each model is trained on `silver_train`, tuned on `silver_val` (C1, C2 and C3)
and evaluated on `silver_val` and, when it has human labels, on `gold_dev`, the
set used to compare models. The run measures training time and artifact size,
then profiles inference in a fresh CPU-only process (load time, latency p50/p95,
CPU time per 1,000 complaints, peak memory). Everything goes to the local
MLflow store, an aggregate report (`<DATA_DIR>/reports/train_local.json`) and a
manifest. Trained models stay in `<DATA_DIR>/models/`, outside Git (G1).

Labels from the offline FakeLLM are refused, unless `--allow-fake-labels` marks
the run as a trial on synthetic data. A trial run is logged with `valid=false`.
"""

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import (
    FileRecord,
    build_manifest,
    file_record,
    git_state,
    write_manifest,
)
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.splits import TRAIN, VAL
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.evaluation.classification import evaluate
from customer_feedback_ai.evaluation.tracking import Tracker
from customer_feedback_ai.labeling.silver import SILVER_TRAIN, SILVER_VAL
from customer_feedback_ai.labeling.taxonomy import TAXONOMY_PATH, Taxonomy, load_taxonomy
from customer_feedback_ai.models.base import LabeledTexts, TopicUrgencyModel
from customer_feedback_ai.models.config import (
    RULES_PATH,
    TRAIN_CONFIG_PATH,
    RulesConfig,
    TrainConfig,
    load_rules,
    load_train_config,
)
from customer_feedback_ai.models.dataset import INPUT_COLUMNS, load_gold_dev, load_silver
from customer_feedback_ai.models.measure import (
    artifact_bytes,
    machine,
    profile_in_subprocess,
    timed,
)
from customer_feedback_ai.models.registry import (
    ARTIFACT_NAMES,
    MODELS,
    build_model,
    require_deep,
)
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, run_cli, write_json

TUNED_ON_SILVER_VAL = frozenset({"c1", "c2", "c3"})
COMPARISON_SET = "gold_dev"


def artifact_records(paths: DataPaths, artifact: Path) -> list[FileRecord]:
    files = (
        sorted(p for p in artifact.rglob("*") if p.is_file()) if artifact.is_dir() else [artifact]
    )
    return [file_record(path, paths.relative(path)) for path in files]


def check_rules(rules: RulesConfig, taxonomy: Taxonomy) -> None:
    """B1 may only answer with topics of the taxonomy."""
    used = {rule.id for rule in rules.topics} | {rules.fallback_topic}
    unknown = sorted(used - set(taxonomy.topic_ids))
    if unknown:
        msg = f"configs/rules.yaml has topics outside the taxonomy: {unknown}"
        raise DataPipelineError(msg)


def _quality(
    model: TopicUrgencyModel, data: LabeledTexts, config: TrainConfig
) -> dict[str, Any] | None:
    if not len(data):
        return None
    topics, urgencies = model.predict(data.texts)
    resamples = config.measurement.bootstrap_resamples
    return evaluate(
        data.topics, topics, data.urgencies, urgencies, resamples=resamples, seed=config.seed
    )


def train_one(
    name: str,
    model: TopicUrgencyModel,
    train: LabeledTexts,
    val: LabeledTexts,
    gold: LabeledTexts,
    config: TrainConfig,
    artifact: Path,
    work_dir: Path,
) -> dict[str, Any]:
    fitted = timed(lambda: model.fit(train, val))
    model.save(artifact)
    result = {
        "params": model.params(),
        "silver_val": _quality(model, val, config),
        "gold_dev": _quality(model, gold, config),
    }
    # The probe loads the saved copy in a fresh process, so it measures exactly
    # what was saved and nothing left over from training.
    probe = profile_in_subprocess(
        name, artifact, val.texts[: config.measurement.latency_samples], work_dir
    )
    return {
        **result,
        "cost": {
            "train_seconds": fitted.seconds,
            "artifact_bytes": artifact_bytes(artifact),
            **probe.as_dict(),
        },
    }


def run(
    paths: DataPaths,
    config: TrainConfig,
    rules: RulesConfig,
    taxonomy: Taxonomy,
    *,
    models: Sequence[str] = MODELS,
    allow_fake_labels: bool = False,
    train_size: int | None = None,
    track: bool = True,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    check_rules(rules, taxonomy)
    names = list(dict.fromkeys(models))
    unknown = sorted(set(names) - set(MODELS))
    if unknown:
        msg = f"unknown models {unknown}; choose from {list(MODELS)}"
        raise DataPipelineError(msg)
    require_deep(names)
    con = connect(paths.tmp_dir)
    silver_train = load_silver(con, paths, SILVER_TRAIN, allow_offline=allow_fake_labels)
    silver_val = load_silver(con, paths, SILVER_VAL, allow_offline=allow_fake_labels)
    train = silver_train.data
    if train_size is not None:
        if train_size > len(train):
            msg = f"--train-size {train_size} is larger than silver_train ({len(train)} labels)"
            raise DataPipelineError(msg)
        # Items are ordered by text hash, so the first n behave like a random sample.
        train = train.head(train_size)
    if not len(train):
        msg = "silver_train has no valid labels"
        raise DataPipelineError(msg)
    val = silver_val.data
    gold, gold_queue = load_gold_dev(paths)

    backends = sorted(set(silver_train.backends) | set(silver_val.backends))
    trial = allow_fake_labels and "fake" in backends
    run_id = now().strftime("%Y%m%dT%H%M%SZ")
    out_dir = paths.models_dir / run_id
    inputs: list[FileRecord] = [
        file_record(path, paths.relative(path))
        for path in (
            silver_train.labels_path,
            silver_val.labels_path,
            paths.splits_dir("silver") / f"{TRAIN}.parquet",
            paths.splits_dir("silver") / f"{VAL}.parquet",
        )
    ] + [
        file_record(path, paths.relative(path))
        for path in (paths.annotation_queue, paths.annotation_labels)
        if path.exists()
    ]
    git = git_state()
    tracker = Tracker(paths.mlflow_dir, enabled=track)

    notes = []
    if trial:
        notes.append("trial run on FakeLLM labels: the numbers are not results")
    if len(gold) < gold_queue:
        notes.append(f"gold_dev has human labels for {len(gold)} of {gold_queue} items")
    if not len(gold):
        notes.append("no gold_dev labels yet (G3): quality only on silver_val")
    tuned = sorted(TUNED_ON_SILVER_VAL & set(names))
    if tuned:
        notes.append(
            f"silver_val also tuned {', '.join(tuned)} (regularization or early stopping), so "
            "their silver_val numbers are optimistic; compare models on gold_dev"
        )
    if len(val) < config.measurement.latency_samples:
        notes.append(
            f"latency from {len(val)} complaints, fewer than the configured "
            f"{config.measurement.latency_samples}"
        )

    results: dict[str, Any] = {}
    outputs: list[FileRecord] = []
    for name in names:
        LOGGER.info("training %s on %d silver labels", name, len(train))
        model = build_model(name, rules, config)
        artifact = out_dir / ARTIFACT_NAMES[name]
        result = train_one(name, model, train, val, gold, config, artifact, paths.tmp_dir)
        del model
        outputs.extend(artifact_records(paths, artifact))
        mlflow_run = tracker.log_run(
            f"{name}-{run_id}",
            params={
                **result["params"],
                "model": name,
                "seed": config.seed,
                "train_labels": len(train),
                "val_labels": len(val),
                "gold_dev_labels": len(gold),
                "label_backends": ",".join(backends),
                "label_models": ",".join(sorted(set(silver_train.models))),
                "input_columns": ",".join(INPUT_COLUMNS),
                "commit": git.commit,
                "dirty": git.dirty,
                **{f"sha256.{Path(r.path).name}": r.sha256 for r in inputs},
            },
            metrics={
                "silver_val": result["silver_val"],
                "gold_dev": result["gold_dev"],
                "cost": result["cost"],
            },
            tags={"run_id": run_id, "valid": str(not trial).lower(), "step": "train_local"},
        )
        results[name] = {
            **result,
            "mlflow_run_id": mlflow_run,
            "artifact": paths.relative(artifact),
        }
        gold_f1 = (result["gold_dev"] or {}).get("topic_macro_f1", {}).get("value")
        val_f1 = (result["silver_val"] or {}).get("topic_macro_f1", {}).get("value")
        LOGGER.info("%s: topic macro-F1 silver_val=%s gold_dev=%s", name, val_f1, gold_f1)

    counts = {
        "silver_train_available": len(silver_train.data),
        "train_labels": len(train),
        "silver_val": len(val),
        "gold_dev_labeled": len(gold),
        "gold_dev_queue": gold_queue,
    }
    report = {
        "run_id": run_id,
        "valid": not trial,
        "label_backends": backends,
        "label_models": sorted(set(silver_train.models) | set(silver_val.models)),
        "counts": counts,
        "input_columns": list(INPUT_COLUMNS),
        "comparison_set": COMPARISON_SET,
        "tuned_on_silver_val": tuned,
        "machine": machine(),
        "models": results,
        "notes": notes,
    }
    report_path = paths.reports_dir / "train_local.json"
    write_json(report, report_path)
    write_manifest(
        build_manifest(
            stage="train_local",
            config={
                "train": config.model_dump(mode="json"),
                "rules_version": rules.version,
                "models": names,
                "train_size": train_size,
                "allow_fake_labels": allow_fake_labels,
            },
            seed=config.seed,
            inputs=inputs,
            outputs=[*outputs, file_record(report_path, paths.relative(report_path))],
            counts=counts,
            details={"run_id": run_id, "valid": not trial, "label_backends": backends},
        ),
        paths.manifest("train_local"),
    )
    for note in notes:
        LOGGER.warning("%s", note)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(MODELS), help="subset of models")
    parser.add_argument(
        "--train-size", type=int, help="use only the first n silver_train labels (learning curves)"
    )
    parser.add_argument(
        "--allow-fake-labels",
        action="store_true",
        help="trial run on FakeLLM labels (synthetic data only); logged as not valid",
    )
    parser.add_argument("--no-mlflow", action="store_true", help="skip the MLflow log")
    parser.add_argument("--config", type=Path, default=TRAIN_CONFIG_PATH)
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    args = parser.parse_args(argv)

    def step() -> dict[str, Any]:
        return run(
            default_paths(),
            load_train_config(args.config),
            load_rules(args.rules),
            load_taxonomy(args.taxonomy),
            models=args.models,
            allow_fake_labels=args.allow_fake_labels,
            train_size=args.train_size,
            track=not args.no_mlflow,
        )

    run_cli(step)


if __name__ == "__main__":
    main()
