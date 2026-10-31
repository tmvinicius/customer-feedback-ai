"""Text normalization used for cleaning, deduplication and hidden companies."""

from collections.abc import Callable

import duckdb
import pytest

from customer_feedback_ai.data import sql

NBSP = "\N{NO-BREAK SPACE}"


def evaluate(
    con: duckdb.DuckDBPyConnection, expression: Callable[[str], str], value: str
) -> object:
    row = con.execute(
        f"SELECT {expression('v')} FROM (SELECT CAST(? AS VARCHAR) AS v)", [value]
    ).fetchone()
    assert row is not None
    return row[0]


def test_case_and_spacing_variants_share_the_dedup_key(con: duckdb.DuckDBPyConnection) -> None:
    original = "Fui cobrado em R$ 10,00.\nQuero o estorno."
    variants = [original.upper(), f"  {original} ", original.replace(" ", NBSP + " "), original]
    keys = {evaluate(con, sql.dedup_key, text) for text in variants}
    assert len(keys) == 1


def test_different_texts_have_different_dedup_keys(con: duckdb.DuckDBPyConnection) -> None:
    first = evaluate(con, sql.dedup_key, "Pedido 123 atrasado")
    second = evaluate(con, sql.dedup_key, "Pedido 124 atrasado")
    assert first != second


def test_cleaning_keeps_tags_and_inner_line_breaks(con: duckdb.DuckDBPyConnection) -> None:
    text = "  Sou [NOME], meu e-mail é [EMAIL].\nAguardo retorno. \n"
    assert (
        evaluate(con, sql.clean_long_text, text)
        == "Sou [NOME], meu e-mail é [EMAIL].\nAguardo retorno."
    )


@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", NBSP])
def test_blank_text_becomes_null(con: duckdb.DuckDBPyConnection, blank: str) -> None:
    assert evaluate(con, sql.clean_long_text, blank) is None


def test_loose_key_ignores_numbers_tags_accents_and_punctuation(
    con: duckdb.DuckDBPyConnection,
) -> None:
    first = evaluate(con, sql.loose_key, "Olá [NOME], o pedido 123 não chegou!")
    second = evaluate(con, sql.loose_key, "OLA [EMAIL], o pedido 98765 nao chegou.")
    assert first == second == "ola o pedido nao chegou"


def test_loose_key_is_null_without_letters(con: duckdb.DuckDBPyConnection) -> None:
    assert evaluate(con, sql.loose_key, "[NOME] 123 456") is None


def test_company_key_normalizes_case_accents_and_spacing(con: duckdb.DuckDBPyConnection) -> None:
    keys = {
        evaluate(con, sql.company_key, name)
        for name in ("Loja Exemplo Ácme", "  loja   exemplo  ACME ", "LOJA EXEMPLO ÁCME")
    }
    assert keys == {"loja exemplo acme"}
