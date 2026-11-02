"""Build the annotation queue for `gold_dev` and `gold_test` (run by `make annotate`).

The queue is built once. Later runs keep it, so labels always point at the same
items; rebuilding needs `--rebuild` and is refused once any label exists.
"""

import argparse
from pathlib import Path

from customer_feedback_ai.data.config import DATA_CONFIG_PATH, DuckDBConfig, load_data_config
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.splits import TEST, TEST_UNSEEN_COMPANY, VAL
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.config import (
    LABELING_CONFIG_PATH,
    LabelingConfig,
    load_labeling_config,
)
from customer_feedback_ai.labeling.gold import LabelStore, build_queue
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, require, run_cli


def run(
    paths: DataPaths,
    config: LabelingConfig,
    duckdb_config: DuckDBConfig | None = None,
    rebuild: bool = False,
) -> bool:
    """Return True when a new queue was written."""
    queue = paths.annotation_queue
    if queue.exists() and not rebuild:
        LOGGER.info("annotation queue already exists: %s", queue)
        return False
    if queue.exists() and LabelStore(paths.annotation_labels).all():
        msg = f"{paths.annotation_labels} already has labels; the queue cannot be rebuilt"
        raise DataPipelineError(msg)
    splits_dir = paths.splits_dir("silver")
    inputs = [
        require(splits_dir / f"{split}.parquet", "Run `make splits` first.")
        for split in (VAL, TEST, TEST_UNSEEN_COMPANY)
    ]
    con = connect(paths.tmp_dir, duckdb_config)
    counts = build_queue(con, splits_dir, queue, config.gold)
    write_manifest(
        build_manifest(
            stage="annotation_queue",
            config=config.gold.model_dump(mode="json"),
            seed=config.gold.seed,
            inputs=[file_record(path, paths.relative(path)) for path in inputs],
            outputs=[
                file_record(
                    queue, paths.relative(queue), rows=counts["gold_dev"] + counts["gold_test"]
                )
            ],
            counts=counts,
        ),
        paths.manifest("annotation_queue"),
    )
    LOGGER.info("annotation queue: %s", counts)
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=LABELING_CONFIG_PATH)
    parser.add_argument("--data-config", type=Path, default=DATA_CONFIG_PATH)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    run_cli(
        lambda: run(
            default_paths(),
            load_labeling_config(args.config),
            load_data_config(args.data_config).duckdb,
            rebuild=args.rebuild,
        )
    )


if __name__ == "__main__":
    main()
