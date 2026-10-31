"""SQL helpers shared by the data pipeline.

Text normalization lives only here, as DuckDB expressions, so that the silver
layer, the splits and the tests all use one definition.
"""

from collections.abc import Iterable
from pathlib import Path

# Whitespace class for RE2 (DuckDB's regex engine), including the no-break space.
_WS = r"[\s\x{00A0}]"


def ident(name: str) -> str:
    """Quote a SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def literal(value: str | Path) -> str:
    """Quote a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def list_literal(values: Iterable[str]) -> str:
    return "[" + ", ".join(literal(value) for value in values) + "]"


def _strip_ws(expr: str) -> str:
    return f"regexp_replace({expr}, '^{_WS}+|{_WS}+$', '', 'g')"


def _collapse_ws(expr: str) -> str:
    return f"regexp_replace({expr}, '{_WS}+', ' ', 'g')"


def clean_long_text(expr: str) -> str:
    """Light cleaning stored in silver: Unicode NFC and no leading or trailing whitespace.

    Line breaks inside the text and anonymization tags such as `[NOME]` are kept.
    Blank strings become NULL.
    """
    return f"nullif({_strip_ws(f'nfc_normalize({expr})')}, '')"


def clean_short_text(expr: str) -> str:
    """Cleaning for categorical text (company, location, status): whitespace collapsed."""
    return f"nullif({_strip_ws(_collapse_ws(f'nfc_normalize({expr})'))}, '')"


def dedup_key(expr: str) -> str:
    """Normalized text that defines exact duplicates: case-folded, whitespace collapsed."""
    return f"lower({_strip_ws(_collapse_ws(f'nfc_normalize({expr})'))})"


def loose_key(expr: str) -> str:
    """Aggressive normalization used to estimate near-duplicates.

    Also removes accents, anonymization tags, digits and punctuation, so complaints
    that differ only by order numbers, dates or names share the same key.
    Returns NULL when nothing is left.
    """
    text = f"strip_accents(lower(nfc_normalize({expr})))"
    without_tags = rf"regexp_replace({text}, '\[[^\]]*\]', ' ', 'g')"
    letters_only = f"regexp_replace({without_tags}, '[^a-z]+', ' ', 'g')"
    return f"nullif({_strip_ws(_collapse_ws(letters_only))}, '')"


def company_key(expr: str) -> str:
    """Normalized company name used for the hidden-company split."""
    return f"nullif(strip_accents(lower({_strip_ws(_collapse_ws(f'nfc_normalize({expr})'))})), '')"


def sha256_of(expr: str) -> str:
    """SHA-256 of an expression, NULL when the expression is NULL."""
    return f"CASE WHEN ({expr}) IS NULL THEN NULL ELSE sha256({expr}) END"
