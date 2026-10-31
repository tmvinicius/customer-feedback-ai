"""Only the complaint text may reach the classifiers (AGENTS.md, rule 5)."""

import pytest

from customer_feedback_ai.data.schema import (
    CLASSIFIER_INPUT_COLUMNS,
    COLUMNS_BY_NAME,
    COMPANY_KEY_COLUMN,
    LOOSE_HASH_COLUMN,
    RAW_COLUMN_NAMES,
    SPLIT_COLUMN,
    TEXT_COLUMN,
    TEXT_HASH_COLUMN,
    FeatureLeakageError,
    FieldUsage,
    check_classifier_inputs,
)

NON_INPUT_COLUMNS = [
    *(name for name in RAW_COLUMN_NAMES if name != TEXT_COLUMN),
    TEXT_HASH_COLUMN,
    LOOSE_HASH_COLUMN,
    COMPANY_KEY_COLUMN,
    SPLIT_COLUMN,
]


def test_schema_has_the_columns_of_the_plan() -> None:
    assert RAW_COLUMN_NAMES == (
        "ID",
        "id_reclamacao",
        "reclamacao_labeled",
        "empresa",
        "data_abertura",
        "localizacao",
        "resposta_labeled",
        "padronizada",
        "status",
        "avaliacao_nota",
        "data_resposta",
        "avaliacao_comentario",
    )


def test_complaint_text_is_the_only_classifier_input() -> None:
    assert CLASSIFIER_INPUT_COLUMNS == (TEXT_COLUMN,)
    assert check_classifier_inputs([TEXT_COLUMN]) == (TEXT_COLUMN,)


@pytest.mark.parametrize("column", NON_INPUT_COLUMNS)
def test_any_other_column_is_rejected(column: str) -> None:
    with pytest.raises(FeatureLeakageError, match=column):
        check_classifier_inputs([TEXT_COLUMN, column])


def test_empty_input_is_rejected() -> None:
    with pytest.raises(FeatureLeakageError):
        check_classifier_inputs([])


def test_fields_known_only_after_opening_are_never_inputs() -> None:
    for name in ("data_resposta", "avaliacao_comentario"):
        assert COLUMNS_BY_NAME[name].usage is FieldUsage.NOT_USED
    for name in ("resposta_labeled", "padronizada", "status", "avaliacao_nota"):
        assert COLUMNS_BY_NAME[name].usage in (
            FieldUsage.RETRIEVAL_CONTENT,
            FieldUsage.RETRIEVAL_FILTER,
        )
