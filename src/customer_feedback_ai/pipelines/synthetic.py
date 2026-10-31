"""`make synthetic-data`: writes an invented corpus to <DATA_DIR>/raw for trying the pipeline.

Use a separate data directory so synthetic and real data never mix:

    make synthetic-data data sample splits DATA_DIR=data/synthetic
"""

import argparse

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.synthetic import write_synthetic_csv
from customer_feedback_ai.pipelines._common import LOGGER, default_paths, run_cli

SYNTHETIC_CSV_NAME = "synthetic_consumerbr.csv"


def run(paths: DataPaths, rows: int, seed: int) -> None:
    output = paths.raw_dir / SYNTHETIC_CSV_NAME
    others = [p.name for p in sorted(paths.raw_dir.glob("*.csv")) if p.name != SYNTHETIC_CSV_NAME]
    if others:
        msg = (
            f"{paths.raw_dir} already has other CSV files {others}. "
            "Use another DATA_DIR, for example DATA_DIR=data/synthetic, to keep real and "
            "synthetic data apart."
        )
        raise FileExistsError(msg)
    write_synthetic_csv(output, rows, seed)
    LOGGER.info("synthetic corpus: %d rows in %s", rows, output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    run_cli(lambda: run(default_paths(), args.rows, args.seed))


if __name__ == "__main__":
    main()
