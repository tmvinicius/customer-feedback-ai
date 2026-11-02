"""Human gold set: annotation queue, label store, re-annotation and export.

- The queue holds `gold_dev` (from `val`) and `gold_test` (from `test`, with about
  25% from `test_unseen_company`). It carries only identifiers and the complaint
  text: no company, no model output, so annotation stays blind.
- Labels go to an append-only JSONL file; the last label of an item in a round
  wins, so corrections never rewrite history.
- About 10% of each set is re-annotated, at least 7 days after the first label,
  without showing the first label, to measure intra-annotator agreement.
- Labels are written only by a person through the annotation tool. Nothing in
  this module calls an LLM (AGENTS.md, rule 3).
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb

from customer_feedback_ai.data import sql
from customer_feedback_ai.data.schema import TEXT_COLUMN, TEXT_HASH_COLUMN
from customer_feedback_ai.data.splits import TEST, TEST_UNSEEN_COMPANY, VAL
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.labeling.agreement import Agreement, agreement
from customer_feedback_ai.labeling.config import GoldConfig
from customer_feedback_ai.labeling.taxonomy import Taxonomy

GOLD_DEV, GOLD_TEST = "gold_dev", "gold_test"
GOLD_SETS: tuple[str, ...] = (GOLD_DEV, GOLD_TEST)
Round = Literal["first", "reannotation"]


@dataclass(frozen=True)
class QueueItem:
    set: str
    position: int
    item_id: str
    source_id: str
    source_split: str
    reannotation: bool
    text: str


@dataclass(frozen=True)
class GoldLabel:
    item_id: str
    set: str
    round: Round
    topic: str
    urgency: str
    doubt: bool
    note: str
    annotator: str
    annotated_at: datetime
    taxonomy_version: str


def _count(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    row = con.execute(f"SELECT count(*) FROM read_parquet({sql.literal(path)})").fetchone()
    assert row is not None
    return int(row[0])


def _pick(path: Path, gold_set: str, source: str, n: int, seed: int) -> str:
    rank = f"sha256({sql.literal(f'{seed}:{gold_set}:')} || {TEXT_HASH_COLUMN})"
    return (
        f"(SELECT '{gold_set}' AS set, '{source}' AS source_split, "
        f"{TEXT_HASH_COLUMN} AS item_id, CAST({sql.ident('ID')} AS VARCHAR) AS source_id, "
        f"{sql.ident(TEXT_COLUMN)} AS text, {rank} AS rank "
        f"FROM read_parquet({sql.literal(path)}) ORDER BY rank LIMIT {int(n)})"
    )


def build_queue(
    con: duckdb.DuckDBPyConnection, splits_dir: Path, output: Path, config: GoldConfig
) -> dict[str, int]:
    """Sample the annotation queue deterministically from the splits."""
    paths = {split: splits_dir / f"{split}.parquet" for split in (VAL, TEST, TEST_UNSEEN_COMPANY)}
    available = {split: _count(con, path) for split, path in paths.items()}
    n_unseen = min(
        round(config.gold_test_size * config.gold_test_unseen_share), available[TEST_UNSEEN_COMPANY]
    )
    n_test = min(config.gold_test_size - n_unseen, available[TEST])
    n_dev = min(config.gold_dev_size, available[VAL])
    if n_dev < config.gold_dev_size or n_test + n_unseen < config.gold_test_size:
        msg = (
            f"not enough rows for the gold sets: val={available[VAL]}, test={available[TEST]}, "
            f"test_unseen_company={available[TEST_UNSEEN_COMPANY]}"
        )
        raise DataPipelineError(msg)
    reannotate = {
        GOLD_DEV: round(n_dev * config.reannotation_fraction),
        GOLD_TEST: round((n_test + n_unseen) * config.reannotation_fraction),
    }
    seed = config.seed
    picks = " UNION ALL ".join(
        [
            _pick(paths[VAL], GOLD_DEV, VAL, n_dev, seed),
            _pick(paths[TEST], GOLD_TEST, TEST, n_test, seed),
            _pick(paths[TEST_UNSEEN_COMPANY], GOLD_TEST, TEST_UNSEEN_COMPANY, n_unseen, seed),
        ]
    )
    reannotation_rank = f"sha256({sql.literal(f'{seed}:reannotation:')} || item_id)"
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT set,
                CAST(row_number() OVER (PARTITION BY set ORDER BY rank) AS INTEGER) AS position,
                item_id, source_id, source_split,
                row_number() OVER (PARTITION BY set ORDER BY {reannotation_rank})
                    <= CASE set WHEN '{GOLD_DEV}' THEN {reannotate[GOLD_DEV]}
                                ELSE {reannotate[GOLD_TEST]} END AS reannotation,
                text
            FROM ({picks})
            ORDER BY set, position
        ) TO {sql.literal(output)} (FORMAT parquet, COMPRESSION zstd)
        """
    )
    return {
        GOLD_DEV: n_dev,
        GOLD_TEST: n_test + n_unseen,
        "gold_test_unseen_company": n_unseen,
        "reannotation_gold_dev": reannotate[GOLD_DEV],
        "reannotation_gold_test": reannotate[GOLD_TEST],
    }


def load_queue(queue: Path) -> list[QueueItem]:
    con = duckdb.connect()
    rows = con.execute(
        "SELECT set, position, item_id, source_id, source_split, reannotation, text "
        f"FROM read_parquet({sql.literal(queue)}) ORDER BY set, position"
    ).fetchall()
    return [
        QueueItem(
            set=str(r[0]),
            position=int(r[1]),
            item_id=str(r[2]),
            source_id=str(r[3]),
            source_split=str(r[4]),
            reannotation=bool(r[5]),
            text=str(r[6]),
        )
        for r in rows
    ]


class LabelStore:
    """Append-only JSONL store of human labels."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, label: GoldLabel) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(label)
        payload["annotated_at"] = label.annotated_at.isoformat()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def all(self) -> list[GoldLabel]:
        if not self.path.exists():
            return []
        labels = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    data = json.loads(line)
                    data["annotated_at"] = datetime.fromisoformat(data["annotated_at"])
                    labels.append(GoldLabel(**data))
        return labels

    def latest(self) -> dict[tuple[str, Round], GoldLabel]:
        """Last label of each item in each round."""
        return {(label.item_id, label.round): label for label in self.all()}


def reannotation_due(
    item: QueueItem,
    latest: dict[tuple[str, Round], GoldLabel],
    now: datetime,
    min_days: int,
) -> bool:
    first = latest.get((item.item_id, "first"))
    return (
        item.reannotation
        and first is not None
        and (item.item_id, "reannotation") not in latest
        and now - first.annotated_at >= timedelta(days=min_days)
    )


def pending_items(
    items: list[QueueItem],
    latest: dict[tuple[str, Round], GoldLabel],
    gold_set: str,
    round_: Round,
    now: datetime,
    min_days: int,
) -> list[QueueItem]:
    """Items still waiting for a label in this set and round, in queue order."""
    in_set = [item for item in items if item.set == gold_set]
    if round_ == "first":
        return [item for item in in_set if (item.item_id, "first") not in latest]
    return [item for item in in_set if reannotation_due(item, latest, now, min_days)]


def export_gold(
    con: duckdb.DuckDBPyConnection,
    items: list[QueueItem],
    latest: dict[tuple[str, Round], GoldLabel],
    outputs: dict[str, Path],
) -> dict[str, int]:
    """Write one Parquet per gold set with the first-round labels."""
    counts = {}
    for gold_set, output in outputs.items():
        rows = [
            (
                item.item_id,
                item.source_id,
                item.source_split,
                item.position,
                item.text,
                label.topic,
                label.urgency,
                label.doubt,
                label.annotator,
                label.annotated_at.isoformat(),
                label.taxonomy_version,
            )
            for item in items
            if item.set == gold_set and (label := latest.get((item.item_id, "first")))
        ]
        con.execute(
            "CREATE OR REPLACE TEMP TABLE gold_export (item_id VARCHAR, source_id VARCHAR, "
            "source_split VARCHAR, position INTEGER, reclamacao_labeled VARCHAR, topic VARCHAR, "
            "urgency VARCHAR, doubt BOOLEAN, annotator VARCHAR, annotated_at VARCHAR, "
            "taxonomy_version VARCHAR)"
        )
        if rows:
            con.executemany(f"INSERT INTO gold_export VALUES ({', '.join(['?'] * 11)})", rows)
        output.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY (SELECT * FROM gold_export ORDER BY position) TO {sql.literal(output)} "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
        counts[gold_set] = len(rows)
    return counts


def _agreement_dict(result: Agreement) -> dict[str, Any]:
    return {"n": result.n, "observed": result.observed, "kappa": result.kappa}


def gold_report(
    items: list[QueueItem],
    latest: dict[tuple[str, Round], GoldLabel],
    config: GoldConfig,
    taxonomy: Taxonomy,
) -> dict[str, Any]:
    """Coverage, class counts, intra-annotator kappa and the plan's alerts."""
    report: dict[str, Any] = {"sets": {}, "alerts": []}
    for gold_set in GOLD_SETS:
        in_set = [item for item in items if item.set == gold_set]
        firsts = [latest[(i.item_id, "first")] for i in in_set if (i.item_id, "first") in latest]
        pairs = [
            (latest[(i.item_id, "first")], latest[(i.item_id, "reannotation")])
            for i in in_set
            if (i.item_id, "first") in latest and (i.item_id, "reannotation") in latest
        ]
        topics = Counter(label.topic for label in firsts)
        urgencies = Counter(label.urgency for label in firsts)
        report["sets"][gold_set] = {
            "items": len(in_set),
            "labeled": len(firsts),
            "complete": len(firsts) == len(in_set),
            "doubts": sum(label.doubt for label in firsts),
            "topics": {topic: topics.get(topic, 0) for topic in taxonomy.topic_ids},
            "urgency": {level: urgencies.get(level, 0) for level in taxonomy.urgency_ids},
            "reannotation": {
                "planned": sum(item.reannotation for item in in_set),
                "topic": _agreement_dict(
                    agreement([a.topic for a, _ in pairs], [b.topic for _, b in pairs])
                ),
                "urgency": _agreement_dict(
                    agreement([a.urgency for a, _ in pairs], [b.urgency for _, b in pairs])
                ),
            },
        }

    dev = report["sets"][GOLD_DEV]
    if dev["complete"]:
        rare = [
            t for t, n in dev["topics"].items() if n < config.min_examples_per_topic_in_gold_dev
        ]
        if rare:
            report["alerts"].append(
                f"topics with fewer than {config.min_examples_per_topic_in_gold_dev} examples in "
                f"gold_dev: {rare}. Review the taxonomy before annotating gold_test."
            )
    test = report["sets"][GOLD_TEST]
    if test["complete"] and test["urgency"]["alta"] < config.min_high_urgency_in_gold_test:
        report["alerts"].append(
            f"gold_test has {test['urgency']['alta']} high-urgency cases, fewer than "
            f"{config.min_high_urgency_in_gold_test}. Build the extra keyword-enriched set."
        )
    return report
