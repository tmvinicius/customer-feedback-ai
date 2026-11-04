"""The interface shared by every local classifier.

Each model predicts the two outputs of the project, topic and urgency, from the
complaint text only (AGENTS.md, rule 5).
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LabeledTexts:
    """Complaint texts with their topic and urgency labels."""

    item_ids: tuple[str, ...]
    texts: tuple[str, ...]
    topics: tuple[str, ...]
    urgencies: tuple[str, ...]

    def __post_init__(self) -> None:
        sizes = {len(self.item_ids), len(self.texts), len(self.topics), len(self.urgencies)}
        if len(sizes) != 1:
            msg = "labeled texts must have the same number of ids, texts and labels"
            raise ValueError(msg)

    def __len__(self) -> int:
        return len(self.texts)

    def head(self, n: int) -> "LabeledTexts":
        return LabeledTexts(self.item_ids[:n], self.texts[:n], self.topics[:n], self.urgencies[:n])


class TopicUrgencyModel(Protocol):
    @property
    def name(self) -> str: ...

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None: ...

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]: ...

    def params(self) -> dict[str, Any]:
        """Hyperparameters and choices made during fit, for the experiment log."""
        ...

    def save(self, path: Path) -> None: ...


def fold(text: str) -> str:
    """Lower case, no accents, single spaces: the form used by keyword rules."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())
