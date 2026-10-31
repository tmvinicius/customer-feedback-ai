"""`make sample`: deterministic dev_sample drawn from silver."""

import argparse
from pathlib import Path

from customer_feedback_ai.data.config import DATA_CONFIG_PATH, DataConfig, load_data_config
from customer_feedback_ai.data.duck import connect, count_rows
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.sample import write_dev_sample
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, require, run_cli


def run(paths: DataPaths, config: DataConfig) -> None:
    silver = require(paths.silver, "Run `make data` first.")
    con = connect(paths.tmp_dir, config.duckdb)
    size, seed = config.sample.dev_sample_size, config.sample.seed
    rows = write_dev_sample(con, silver, paths.dev_sample, size, seed)
    write_manifest(
        build_manifest(
            stage="dev_sample",
            config=config.sample.model_dump(mode="json"),
            seed=seed,
            inputs=[file_record(silver, paths.relative(silver), rows=count_rows(con, silver))],
            outputs=[file_record(paths.dev_sample, paths.relative(paths.dev_sample), rows=rows)],
            counts={"rows": rows, "requested_rows": size},
        ),
        paths.manifest("dev_sample"),
    )
    LOGGER.info("dev_sample: %d rows in %s", rows, paths.dev_sample)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DATA_CONFIG_PATH)
    args = parser.parse_args(argv)
    run_cli(lambda: run(default_paths(), load_data_config(args.config)))


if __name__ == "__main__":
    main()
