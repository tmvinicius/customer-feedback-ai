"""`make taxonomy-sample`: complaints from train for the maintainer to read before G2."""

import argparse
from pathlib import Path
from typing import get_args

from customer_feedback_ai.data.config import DATA_CONFIG_PATH, DataConfig, load_data_config
from customer_feedback_ai.data.duck import connect, count_rows
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths, SplitSource
from customer_feedback_ai.data.sample import write_taxonomy_review_sample
from customer_feedback_ai.data.splits import TRAIN
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, require, run_cli


def run(paths: DataPaths, config: DataConfig, source: SplitSource = "silver") -> None:
    train = require(paths.splits_dir(source) / f"{TRAIN}.parquet", "Run `make splits` first.")
    con = connect(paths.tmp_dir, config.duckdb)
    size, seed = config.sample.taxonomy_review_size, config.sample.seed
    output = paths.taxonomy_review_sample
    rows = write_taxonomy_review_sample(con, train, output, size, seed)
    write_manifest(
        build_manifest(
            stage="taxonomy_review_sample",
            config={"source": source, **config.sample.model_dump(mode="json")},
            seed=seed,
            inputs=[file_record(train, paths.relative(train), rows=count_rows(con, train))],
            outputs=[file_record(output, paths.relative(output), rows=rows)],
            counts={"rows": rows, "requested_rows": size},
        ),
        paths.manifest("taxonomy_review_sample"),
    )
    LOGGER.info("taxonomy review sample: %d complaints in %s", rows, output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=get_args(SplitSource), default="silver")
    parser.add_argument("--config", type=Path, default=DATA_CONFIG_PATH)
    args = parser.parse_args(argv)
    run_cli(lambda: run(default_paths(), load_data_config(args.config), source=args.source))


if __name__ == "__main__":
    main()
