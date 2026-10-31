"""Expected ConsumerBR schema and the allowed use of each field (AGENTS.md, section 6).

Only `reclamacao_labeled` may feed the classifiers. Every other field is either
an identifier, a split or retrieval key, or information that only exists after
the complaint was opened, which would leak the outcome into the inputs.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ColumnType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"


class FieldUsage(StrEnum):
    IDENTIFIER = "identifier"
    CLASSIFIER_INPUT = "classifier_input"
    SPLIT_RETRIEVAL_ANALYSIS = "split_retrieval_analysis"
    SPLIT_ANALYSIS = "split_analysis"
    ANALYSIS = "analysis"
    RETRIEVAL_CONTENT = "retrieval_content"
    RETRIEVAL_FILTER = "retrieval_filter"
    NOT_USED = "not_used"


@dataclass(frozen=True)
class RawColumn:
    name: str
    type: ColumnType
    usage: FieldUsage


RAW_COLUMNS: tuple[RawColumn, ...] = (
    RawColumn("ID", ColumnType.TEXT, FieldUsage.IDENTIFIER),
    RawColumn("id_reclamacao", ColumnType.INTEGER, FieldUsage.IDENTIFIER),
    RawColumn("reclamacao_labeled", ColumnType.TEXT, FieldUsage.CLASSIFIER_INPUT),
    RawColumn("empresa", ColumnType.TEXT, FieldUsage.SPLIT_RETRIEVAL_ANALYSIS),
    RawColumn("data_abertura", ColumnType.TIMESTAMP, FieldUsage.SPLIT_ANALYSIS),
    RawColumn("localizacao", ColumnType.TEXT, FieldUsage.ANALYSIS),
    RawColumn("resposta_labeled", ColumnType.TEXT, FieldUsage.RETRIEVAL_CONTENT),
    RawColumn("padronizada", ColumnType.BOOLEAN, FieldUsage.RETRIEVAL_FILTER),
    RawColumn("status", ColumnType.TEXT, FieldUsage.RETRIEVAL_FILTER),
    RawColumn("avaliacao_nota", ColumnType.INTEGER, FieldUsage.RETRIEVAL_FILTER),
    RawColumn("data_resposta", ColumnType.TIMESTAMP, FieldUsage.NOT_USED),
    RawColumn("avaliacao_comentario", ColumnType.TEXT, FieldUsage.NOT_USED),
)

RAW_COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in RAW_COLUMNS)
COLUMNS_BY_NAME: dict[str, RawColumn] = {column.name: column for column in RAW_COLUMNS}

TEXT_COLUMN = "reclamacao_labeled"
CLASSIFIER_INPUT_COLUMNS: tuple[str, ...] = tuple(
    column.name for column in RAW_COLUMNS if column.usage is FieldUsage.CLASSIFIER_INPUT
)

# Columns added by the silver and gold layers. None of them is a classifier input.
TEXT_HASH_COLUMN = "text_hash"
LOOSE_HASH_COLUMN = "loose_hash"
COMPANY_KEY_COLUMN = "company_key"
SPLIT_COLUMN = "split"


class FeatureLeakageError(ValueError):
    """Raised when a classifier would receive a column other than the complaint text."""


def check_classifier_inputs(columns: Iterable[str]) -> tuple[str, ...]:
    """Return the columns unchanged if they are allowed as classifier inputs, else raise."""
    selected = tuple(columns)
    forbidden = sorted(set(selected) - set(CLASSIFIER_INPUT_COLUMNS))
    if forbidden:
        msg = f"columns not allowed as classifier inputs: {forbidden}"
        raise FeatureLeakageError(msg)
    if not selected:
        msg = "at least one classifier input column is required"
        raise FeatureLeakageError(msg)
    return selected
