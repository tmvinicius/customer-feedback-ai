"""B0 (majority class) and B1 (keyword rules): the floor of the comparison."""

import json
import re
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

    @classmethod
    def load(cls, path: Path) -> "MajorityBaseline":
        saved = json.loads(path.read_text(encoding="utf-8"))
        model = cls()
        model.topic, model.urgency = saved["majority_topic"], saved["majority_urgency"]
        return model


def _most_common(labels: Sequence[str]) -> str:
    counts = Counter(labels)
    best = max(counts.values())
    return sorted(label for label, count in counts.items() if count == best)[0]


STEM = "*"


def keyword_pattern(keywords: Sequence[str]) -> re.Pattern[str]:
    """One regex for a keyword list, matched on folded text.

    A keyword matches whole words only; a trailing `*` makes it a stem that
    accepts any continuation. Matches always start at a word boundary.
    """
    parts = []
    for keyword in keywords:
        stem = keyword.endswith(STEM)
        body = re.escape(fold(keyword.removesuffix(STEM)))
        parts.append(body if stem else rf"{body}(?![a-z0-9])")
    return re.compile(rf"(?<![a-z0-9])(?:{'|'.join(parts)})")


class KeywordRules:
    """B1: the first topic whose keyword appears in the text; urgency by keyword lists.

    No training: `fit` does nothing, so the rules never see the labels.
    """

    name = "b1"

    def __init__(self, rules: RulesConfig):
        self.rules = rules
        self._topics = [(rule.id, keyword_pattern(rule.keywords)) for rule in rules.topics]
        self._high = keyword_pattern(rules.urgency.alta) if rules.urgency.alta else None
        self._low = keyword_pattern(rules.urgency.baixa) if rules.urgency.baixa else None

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        return None

    def predict_one(self, text: str) -> tuple[str, str]:
        folded = fold(text)
        topic = next(
            (topic for topic, pattern in self._topics if pattern.search(folded)),
            self.rules.fallback_topic,
        )
        if self._high is not None and self._high.search(folded):
            urgency = "alta"
        elif self._low is not None and self._low.search(folded):
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

    @classmethod
    def load(cls, path: Path) -> "KeywordRules":
        return cls(RulesConfig.model_validate_json(path.read_text(encoding="utf-8")))
