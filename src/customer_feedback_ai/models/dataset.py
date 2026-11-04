"""Training and evaluation sets for the local models.

- `silver_train` and `silver_val`: valid LLM labels joined with the complaint text
  of the train and val splits. Labels from the offline `FakeLLM` are refused
  unless the run is explicitly marked as a trial.
- `gold_dev`: the human first-round labels.

Only `reclamacao_labeled` is read as model input (AGENTS.md, rule 5).
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.schema import TEXT_COLUMN, TEXT_HASH_COLUMN, check_classifier_inputs
from customer_feedback_ai.data.splits import TRAIN, VAL
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.gold import GOLD_DEV, LabelStore, load_queue
from customer_feedback_ai.labeling.silver import SILVER_TRAIN, SILVER_VAL
from customer_feedback_ai.models.base import LabeledTexts

INPUT_COLUMNS = check_classifier_inputs([TEXT_COLUMN])
OFFLINE_BACKENDS = frozenset({"fake"})


@dataclass(frozen=True)
class SilverSet:
    data: LabeledTexts
    backends: tuple[str, ...]
    models: tuple[str, ...]
    labels_path: Path


def load_silver(
    con: duckdb.DuckDBPyConnection, paths: DataPaths, set_name: str, *, allow_offline: bool = False
) -> SilverSet:
    """Valid silver labels with the complaint text, ordered by item id."""
    labels = paths.silver_labels_dir / f"{set_name}.parquet"
    if not labels.exists():
        msg = f"{labels} not found. Run `make label-silver` first."
        raise DataPipelineError(msg)
    split = {SILVER_TRAIN: TRAIN, SILVER_VAL: VAL}[set_name]
    texts = paths.splits_dir("silver") / f"{split}.parquet"
    (text_column,) = INPUT_COLUMNS
    rows = con.execute(
        f"SELECT l.item_id, t.{sql.ident(text_column)}, l.topic, l.urgency, l.backend, l.model "
        f"FROM read_parquet({sql.literal(labels)}) AS l "
        f"JOIN read_parquet({sql.literal(texts)}) AS t ON t.{TEXT_HASH_COLUMN} = l.item_id "
        "WHERE l.label_status = 'valid' ORDER BY l.item_id"
    ).fetchall()
    backends = tuple(sorted({str(r[4]) for r in rows}))
    if not allow_offline and OFFLINE_BACKENDS & set(backends):
        msg = (
            f"{set_name} has labels from the offline FakeLLM ({backends}). "
            "They are not real labels; use --allow-fake-labels (make train-local "
            "ALLOW_FAKE_LABELS=1) only for trial runs on synthetic data."
        )
        raise DataPipelineError(msg)
    data = LabeledTexts(
        tuple(str(r[0]) for r in rows),
        tuple(str(r[1]) for r in rows),
        tuple(str(r[2]) for r in rows),
        tuple(str(r[3]) for r in rows),
    )
    return SilverSet(data, backends, tuple(sorted({str(r[5]) for r in rows})), labels)


def load_gold_dev(paths: DataPaths) -> tuple[LabeledTexts, int]:
    """Human-labeled `gold_dev` items and the number of items in the queue."""
    if not paths.annotation_queue.exists():
        return LabeledTexts((), (), (), ()), 0
    items = [item for item in load_queue(paths.annotation_queue) if item.set == GOLD_DEV]
    latest = LabelStore(paths.annotation_labels).latest()
    labeled = [
        (item, latest[(item.item_id, "first")])
        for item in items
        if (item.item_id, "first") in latest
    ]
    return (
        LabeledTexts(
            tuple(item.item_id for item, _ in labeled),
            tuple(item.text for item, _ in labeled),
            tuple(label.topic for _, label in labeled),
            tuple(label.urgency for _, label in labeled),
        ),
        len(items),
    )
