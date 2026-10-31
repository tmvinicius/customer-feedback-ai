"""`make data`: raw CSV -> bronze -> silver, with manifests and a lean profile."""

import argparse
from dataclasses import asdict
from pathlib import Path

from customer_feedback_ai.data.clean import build_silver
from customer_feedback_ai.data.config import DATA_CONFIG_PATH, DataConfig, load_data_config
from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.eda import compare_with_paper, profile
from customer_feedback_ai.data.ingest import validate_csv, write_bronze
from customer_feedback_ai.data.manifest import build_manifest, file_record, write_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, run_cli, write_json


def run(paths: DataPaths, config: DataConfig, raw: Path | None = None) -> None:
    csv_path = raw or paths.find_raw_csv()
    con = connect(paths.tmp_dir, config.duckdb)
    config_dump = config.model_dump(mode="json")

    LOGGER.info("validating %s", csv_path)
    ingest = validate_csv(con, csv_path, config.csv, config.validation)
    LOGGER.info("writing bronze: %d rows", ingest.rows)
    write_bronze(con, csv_path, paths.bronze, config.csv)
    write_manifest(
        build_manifest(
            stage="bronze",
            config=config_dump,
            inputs=[file_record(csv_path, paths.relative(csv_path))],
            outputs=[file_record(paths.bronze, paths.relative(paths.bronze), rows=ingest.rows)],
            counts={
                "rows": ingest.rows,
                "missing_ids": ingest.missing_ids,
                "duplicate_ids": ingest.duplicate_ids,
            },
            details={
                "cast_failures": ingest.cast_failures,
                "non_null": ingest.non_null,
                "extra_columns": list(ingest.extra_columns),
            },
        ),
        paths.manifest("bronze"),
    )

    bronze_profile = profile(con, paths.bronze)
    comparison = (
        compare_with_paper(bronze_profile, config.paper_reference)
        if config.paper_reference is not None
        else []
    )
    write_json(
        {"profile": bronze_profile, "paper_comparison": comparison},
        paths.eda_dir / "bronze_profile.json",
    )
    for item in comparison:
        if not item["within_tolerance"]:
            LOGGER.warning(
                "differs from the paper: %s (paper=%s, observed=%s)",
                item["metric"],
                item["paper"],
                item["observed"],
            )

    LOGGER.info("writing silver")
    silver = build_silver(con, paths.bronze, paths.silver)
    write_manifest(
        build_manifest(
            stage="silver",
            config=config_dump,
            inputs=[file_record(paths.bronze, paths.relative(paths.bronze), rows=silver.rows_in)],
            outputs=[file_record(paths.silver, paths.relative(paths.silver), rows=silver.rows_out)],
            counts=asdict(silver),
        ),
        paths.manifest("silver"),
    )
    write_json({"profile": profile(con, paths.silver)}, paths.eda_dir / "silver_profile.json")
    LOGGER.info(
        "silver: %d rows (dropped %d empty, %d duplicates)",
        silver.rows_out,
        silver.dropped_empty_text,
        silver.dropped_duplicates,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw", type=Path, help="CSV file; default: the only CSV in <DATA_DIR>/raw"
    )
    parser.add_argument("--config", type=Path, default=DATA_CONFIG_PATH)
    args = parser.parse_args(argv)
    run_cli(lambda: run(default_paths(), load_data_config(args.config), raw=args.raw))


if __name__ == "__main__":
    main()
