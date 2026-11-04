"""B0 (majority class) and B1 (keyword rules): the floor of the comparison."""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from customer_feedback_ai.models.base import LabeledTexts, fold
from customer_feedback_ai.models.config import RulesConfig


class MajorityBaseline:
    """B0: always the most frequent topic and urgency of the training labels."""

    name = "b0"

    def __init__(self) -> None:
        self.topic: str | None = None
        self.urgency: str | None = None

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        if not len(train):
            msg = "cannot fit on an empty training set"
            raise ValueError(msg)
        # Ties go to the label that sorts first, so the result does not depend on order.
        self.topic = _most_common(train.topics)
        self.urgency = _most_common(train.urgencies)

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        if self.topic is None or self.urgency is None:
            msg = "fit the model before predicting"
            raise RuntimeError(msg)
        return [self.topic] * len(texts), [self.urgency] * len(texts)

    def params(self) -> dict[str, Any]:
        return {"majority_topic": self.topic, "majority_urgency": self.urgency}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.params(), ensure_ascii=False), encoding="utf-8")


def _most_common(labels: Sequence[str]) -> str:
    counts = Counter(labels)
    best = max(counts.values())
    return sorted(label for label, count in counts.items() if count == best)[0]


class KeywordRules:
    """B1: the first topic whose keyword appears in the text; urgency by keyword lists.

    No training: `fit` does nothing, so the rules never see the labels.
    """

    name = "b1"

    def __init__(self, rules: RulesConfig):
        self.rules = rules
        self._topics = [(rule.id, tuple(fold(k) for k in rule.keywords)) for rule in rules.topics]
        self._high = tuple(fold(k) for k in rules.urgency.alta)
        self._low = tuple(fold(k) for k in rules.urgency.baixa)

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        return None

    def predict_one(self, text: str) -> tuple[str, str]:
        folded = fold(text)
        topic = next(
            (topic for topic, keys in self._topics if any(k in folded for k in keys)),
            self.rules.fallback_topic,
        )
        if any(k in folded for k in self._high):
            urgency = "alta"
        elif any(k in folded for k in self._low):
            urgency = "baixa"
        else:
            urgency = self.rules.urgency.default
        return topic, urgency

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        pairs = [self.predict_one(text) for text in texts]
        return [t for t, _ in pairs], [u for _, u in pairs]

    def params(self) -> dict[str, Any]:
        return {"rules_version": self.rules.version, "topic_rules": len(self._topics)}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.rules.model_dump_json(indent=2), encoding="utf-8")
