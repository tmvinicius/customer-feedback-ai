"""The synthetic corpus is deterministic and exercises the pipeline's traps."""

from pathlib import Path

import pytest

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.schema import RAW_COLUMN_NAMES
from customer_feedback_ai.data.synthetic import generate_rows, write_synthetic_csv
from customer_feedback_ai.pipelines import synthetic as synthetic_pipeline


def test_same_seed_same_rows() -> None:
    assert list(generate_rows(200, seed=3)) == list(generate_rows(200, seed=3))
    assert list(generate_rows(200, seed=3)) != list(generate_rows(200, seed=4))


def test_rows_follow_the_schema_and_include_traps() -> None:
    rows = list(generate_rows(2_000, seed=5))
    texts = [row["reclamacao_labeled"].strip().lower() for row in rows]

    assert all(tuple(row) == RAW_COLUMN_NAMES for row in rows)
    assert any(row["data_abertura"] == "" for row in rows)
    assert any(text == "" for text in texts)
    assert len(set(texts)) < len(texts)
    assert any("[NOME]" in row["reclamacao_labeled"] for row in rows)


def test_csv_is_byte_identical_for_the_same_seed(tmp_path: Path) -> None:
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    write_synthetic_csv(first, 300, seed=9)
    write_synthetic_csv(second, 300, seed=9)
    assert first.read_bytes() == second.read_bytes()


def test_refuses_to_mix_with_other_raw_files(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    paths.raw_dir.mkdir(parents=True)
    (paths.raw_dir / "consumerbr.csv").write_text("ID\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="DATA_DIR"):
        synthetic_pipeline.run(paths, rows=10, seed=1)
