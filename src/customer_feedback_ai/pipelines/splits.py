"""`make splits`: temporal splits and hidden companies, with integrity checks."""

import argparse
from pathlib import Path
from typing import get_args

from customer_feedback_ai.data.config import (
    DATA_CONFIG_PATH,
    SPLITS_CONFIG_PATH,
    DuckDBConfig,
    SplitsConfig,
    load_data_config,
    load_splits_config,
)
from customer_feedback_ai.data.duck import connect, count_rows
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths, SplitSource
from customer_feedback_ai.data.splits import SplitResult, build_splits
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, require, run_cli


def manifest_stage(source: SplitSource) -> str:
    return "splits" if source == "silver" else "splits_dev_sample"


def run(
    paths: DataPaths,
    config: SplitsConfig,
    source: SplitSource = "silver",
    duckdb_config: DuckDBConfig | None = None,
) -> SplitResult:
    hint = "Run `make data`." if source == "silver" else "Run `make sample`."
    input_path = require(paths.split_input(source), hint)
    con = connect(paths.tmp_dir, duckdb_config)
    result = build_splits(con, input_path, paths.splits_dir(source), config)
    write_manifest(
        build_manifest(
            stage=manifest_stage(source),
            config=config.model_dump(mode="json"),
            inputs=[
                file_record(
                    input_path, paths.relative(input_path), rows=count_rows(con, input_path)
                )
            ],
            outputs=[
                file_record(path, paths.relative(path), rows=result.rows[split])
                for split, path in result.paths.items()
            ],
            counts={
                **{f"rows_{split}": n for split, n in result.rows.items()},
                "excluded_missing_date": result.excluded_missing_date,
                "excluded_hidden_company_before_test": result.excluded_hidden_company_before_test,
                "excluded_outside_windows": result.excluded_outside_windows,
                "companies": result.companies,
                "hidden_companies": result.hidden_companies,
            },
            details={"checks": result.checks},
        ),
        paths.manifest(manifest_stage(source)),
    )
    LOGGER.info(
        "splits from %s: %s; excluded: %d without date, %d hidden-company rows before test",
        source,
        result.rows,
        result.excluded_missing_date,
        result.excluded_hidden_company_before_test,
    )
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=get_args(SplitSource), default="silver")
    parser.add_argument("--config", type=Path, default=SPLITS_CONFIG_PATH)
    parser.add_argument("--data-config", type=Path, default=DATA_CONFIG_PATH)
    args = parser.parse_args(argv)
    run_cli(
        lambda: run(
            default_paths(),
            load_splits_config(args.config),
            source=args.source,
            duckdb_config=load_data_config(args.data_config).duckdb,
        )
    )


if __name__ == "__main__":
    main()
