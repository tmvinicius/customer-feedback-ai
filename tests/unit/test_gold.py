"""Gold set: blind queue, append-only labels, re-annotation timing, export and report."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from customer_feedback_ai.data.manifest import sha256_file
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.sql import literal
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.gold import (
    GOLD_DEV,
    GOLD_TEST,
    GoldLabel,
    LabelStore,
    QueueItem,
    Round,
    build_queue,
    export_gold,
    gold_report,
    load_queue,
    pending_items,
)
from customer_feedback_ai.labeling.taxonomy import Taxonomy, load_taxonomy
from customer_feedback_ai.pipelines import gold_report as gold_report_pipeline
from customer_feedback_ai.pipelines import gold_sample as gold_sample_pipeline

from .conftest import REPO_ROOT, SMALL_LABELING

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


def label(
    item: QueueItem,
    round_: Round = "first",
    topic: str = "cancelamento",
    urgency: str = "media",
    at: datetime = T0,
) -> GoldLabel:
    return GoldLabel(
        item_id=item.item_id,
        set=item.set,
        round=round_,
        topic=topic,
        urgency=urgency,
        doubt=False,
        note="",
        annotator="teste",
        annotated_at=at,
        taxonomy_version="0.1.0",
    )


def split_hashes(paths: DataPaths, split: str) -> set[str]:
    path = paths.splits_dir("silver") / f"{split}.parquet"
    rows = (
        duckdb.connect().execute(f"SELECT text_hash FROM read_parquet({literal(path)})").fetchall()
    )
    return {str(r[0]) for r in rows}


# --- queue -----------------------------------------------------------------------


def test_queue_sizes_and_sources(labeling_paths: DataPaths) -> None:
    items = load_queue(labeling_paths.annotation_queue)
    dev = [i for i in items if i.set == GOLD_DEV]
    test = [i for i in items if i.set == GOLD_TEST]

    assert len(dev) == 40
    assert len(test) == 60
    assert sum(i.source_split == "test_unseen_company" for i in test) == 15
    assert {i.item_id for i in dev} <= split_hashes(labeling_paths, "val")
    assert {i.item_id for i in test if i.source_split == "test"} <= split_hashes(
        labeling_paths, "test"
    )
    assert sum(i.reannotation for i in dev) == 4
    assert sum(i.reannotation for i in test) == 6
    assert [i.position for i in dev] == list(range(1, 41))


def test_queue_is_blind(labeling_paths: DataPaths) -> None:
    con = duckdb.connect()
    columns = [
        r[0]
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({literal(labeling_paths.annotation_queue)})"
        ).fetchall()
    ]
    assert columns == [
        "set",
        "position",
        "item_id",
        "source_id",
        "source_split",
        "reannotation",
        "text",
    ]


def test_queue_is_deterministic(labeling_paths: DataPaths, tmp_path: Path) -> None:
    again = tmp_path / "queue.parquet"
    build_queue(duckdb.connect(), labeling_paths.splits_dir("silver"), again, SMALL_LABELING.gold)
    assert sha256_file(again) == sha256_file(labeling_paths.annotation_queue)


def test_queue_needs_enough_rows(labeling_paths: DataPaths, tmp_path: Path) -> None:
    huge = SMALL_LABELING.gold.model_copy(update={"gold_dev_size": 10**6})
    with pytest.raises(DataPipelineError, match="not enough rows"):
        build_queue(
            duckdb.connect(), labeling_paths.splits_dir("silver"), tmp_path / "q.parquet", huge
        )


def test_queue_is_kept_and_never_rebuilt_after_labeling(labeling_paths: DataPaths) -> None:
    assert gold_sample_pipeline.run(labeling_paths, SMALL_LABELING) is False
    assert gold_sample_pipeline.run(labeling_paths, SMALL_LABELING, rebuild=True) is True

    item = load_queue(labeling_paths.annotation_queue)[0]
    LabelStore(labeling_paths.annotation_labels).append(label(item))
    with pytest.raises(DataPipelineError, match="already has labels"):
        gold_sample_pipeline.run(labeling_paths, SMALL_LABELING, rebuild=True)


# --- labels and rounds -----------------------------------------------------------


def test_last_label_of_a_round_wins(labeling_paths: DataPaths) -> None:
    item = load_queue(labeling_paths.annotation_queue)[0]
    store = LabelStore(labeling_paths.annotation_labels)
    store.append(label(item, topic="cancelamento"))
    store.append(label(item, topic="reembolso_estorno", at=T0 + timedelta(minutes=1)))

    assert len(store.all()) == 2
    assert store.latest()[(item.item_id, "first")].topic == "reembolso_estorno"


def test_reannotation_opens_after_the_minimum_delay(labeling_paths: DataPaths) -> None:
    items = load_queue(labeling_paths.annotation_queue)
    store = LabelStore(labeling_paths.annotation_labels)
    flagged = next(i for i in items if i.set == GOLD_DEV and i.reannotation)
    store.append(label(flagged))
    min_days = SMALL_LABELING.gold.reannotation_min_days

    def due(now: datetime) -> list[QueueItem]:
        return pending_items(items, store.latest(), GOLD_DEV, "reannotation", now, min_days)

    assert due(T0 + timedelta(days=6, hours=23)) == []
    assert due(T0 + timedelta(days=7)) == [flagged]
    store.append(label(flagged, round_="reannotation", at=T0 + timedelta(days=8)))
    assert due(T0 + timedelta(days=9)) == []


def test_first_round_pending_shrinks(labeling_paths: DataPaths) -> None:
    items = load_queue(labeling_paths.annotation_queue)
    store = LabelStore(labeling_paths.annotation_labels)
    before = pending_items(items, store.latest(), GOLD_DEV, "first", T0, 7)
    store.append(label(before[0]))
    after = pending_items(items, store.latest(), GOLD_DEV, "first", T0, 7)
    assert after == before[1:]


# --- export and report -----------------------------------------------------------


def label_all(paths: DataPaths, taxonomy: Taxonomy, gold_set: str, urgency: str = "media") -> None:
    store = LabelStore(paths.annotation_labels)
    items = [i for i in load_queue(paths.annotation_queue) if i.set == gold_set]
    topics = taxonomy.topic_ids
    for n, item in enumerate(items):
        store.append(label(item, topic=topics[n % 3], urgency=urgency))
        if item.reannotation:
            second = topics[n % 3] if n % 2 else topics[(n + 1) % 3]
            store.append(
                label(
                    item, "reannotation", topic=second, urgency=urgency, at=T0 + timedelta(days=8)
                )
            )


def test_report_counts_labels_and_measures_kappa(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    items = load_queue(labeling_paths.annotation_queue)
    report = gold_report(
        items, LabelStore(labeling_paths.annotation_labels).latest(), SMALL_LABELING.gold, taxonomy
    )

    dev = report["sets"][GOLD_DEV]
    assert dev["labeled"] == dev["items"] == 40
    assert dev["complete"] is True
    assert sum(dev["topics"].values()) == 40
    assert dev["reannotation"]["topic"]["n"] == 4
    assert dev["reannotation"]["topic"]["kappa"] is not None
    assert report["sets"][GOLD_TEST]["complete"] is False
    assert any("fewer than 5 examples in gold_dev" in alert for alert in report["alerts"])


def test_report_flags_too_few_high_urgency_cases(
    labeling_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    label_all(labeling_paths, taxonomy, GOLD_TEST, urgency="baixa")
    items = load_queue(labeling_paths.annotation_queue)
    report = gold_report(
        items, LabelStore(labeling_paths.annotation_labels).latest(), SMALL_LABELING.gold, taxonomy
    )
    assert any("high-urgency" in alert for alert in report["alerts"])


def test_export_writes_first_round_labels(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    items = load_queue(labeling_paths.annotation_queue)
    outputs = {
        GOLD_DEV: labeling_paths.gold_set(GOLD_DEV),
        GOLD_TEST: labeling_paths.gold_set(GOLD_TEST),
    }
    counts = export_gold(
        duckdb.connect(), items, LabelStore(labeling_paths.annotation_labels).latest(), outputs
    )

    assert counts == {GOLD_DEV: 40, GOLD_TEST: 0}
    row = (
        duckdb.connect()
        .execute(
            "SELECT count(*), count(DISTINCT item_id) "
            f"FROM read_parquet({literal(outputs[GOLD_DEV])})"
        )
        .fetchone()
    )
    assert row == (40, 40)


def test_report_pipeline_writes_files(labeling_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    report = gold_report_pipeline.run(labeling_paths, SMALL_LABELING, taxonomy)

    assert labeling_paths.gold_report.exists()
    assert labeling_paths.manifest("gold_sets").exists()
    assert labeling_paths.gold_set(GOLD_DEV).exists()
    assert "silver_vs_gold_dev" not in report
