"""C1: TF-IDF of words and characters + logistic regression (AGENTS.md, section 8).

One vectorizer is fitted on the training texts and shared by two classifiers, one
for topic and one for urgency. The regularization strength of each classifier is
chosen on `silver_val` by macro-F1, never on `gold_dev` or `test`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from customer_feedback_ai.evaluation.metrics import macro_f1
from customer_feedback_ai.models.base import LabeledTexts
from customer_feedback_ai.models.config import C1Config


class _Constant:
    """Stand-in classifier when the training labels have a single class."""

    def __init__(self, label: str):
        self.label = label

    def predict(self, features: Any) -> list[str]:
        return [self.label] * features.shape[0]


class TfidfLogReg:
    name = "c1"

    def __init__(self, config: C1Config, seed: int):
        self.config = config
        self.seed = seed
        self.vectorizer: FeatureUnion | None = None
        self.topic_clf: Any = None
        self.urgency_clf: Any = None
        self.chosen_c: dict[str, float | None] = {}
        self.val_macro_f1: dict[str, dict[str, float | None]] = {}

    def _vectorizer(self) -> FeatureUnion:
        cfg = self.config
        return FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
                        lowercase=True,
                        strip_accents="unicode",
                        ngram_range=cfg.word_ngrams,
                        min_df=cfg.min_df,
                        max_features=cfg.max_features_word,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "char",
                    TfidfVectorizer(
                        lowercase=True,
                        strip_accents="unicode",
                        analyzer="char_wb",
                        ngram_range=cfg.char_ngrams,
                        min_df=cfg.min_df,
                        max_features=cfg.max_features_char,
                        sublinear_tf=True,
                    ),
                ),
            ]
        )

    def _classifier(self, c: float) -> LogisticRegression:
        return LogisticRegression(
            C=c,
            class_weight=self.config.class_weight,
            max_iter=self.config.max_iter,
            random_state=self.seed,
        )

    def _fit_head(
        self,
        head: str,
        train_x: Any,
        train_y: Sequence[str],
        val_x: Any,
        val_y: Sequence[str] | None,
    ) -> Any:
        if len(set(train_y)) < 2:
            self.chosen_c[head] = None
            return _Constant(train_y[0])
        grid = self.config.c_grid if val_y is not None else self.config.c_grid[:1]
        best: tuple[float, float, Any] | None = None
        scores: dict[str, float | None] = {}
        for c in grid:
            clf = self._classifier(c).fit(train_x, list(train_y))
            score = macro_f1(val_y, list(clf.predict(val_x))) if val_y is not None else None
            scores[str(c)] = score
            # Ties keep the smaller C (stronger regularization), the earlier grid value.
            if best is None or (score or 0.0) > best[0]:
                best = (score or 0.0, c, clf)
        assert best is not None
        self.chosen_c[head] = best[1]
        self.val_macro_f1[head] = scores
        return best[2]

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        self.vectorizer = self._vectorizer()
        train_x = self.vectorizer.fit_transform(train.texts)
        val_x = self.vectorizer.transform(val.texts) if val is not None and len(val) else None
        has_val = val_x is not None and val is not None
        self.topic_clf = self._fit_head(
            "topic", train_x, train.topics, val_x, val.topics if has_val and val else None
        )
        self.urgency_clf = self._fit_head(
            "urgency", train_x, train.urgencies, val_x, val.urgencies if has_val and val else None
        )

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        if self.vectorizer is None:
            msg = "fit the model before predicting"
            raise RuntimeError(msg)
        features = self.vectorizer.transform(list(texts))
        return (
            [str(label) for label in self.topic_clf.predict(features)],
            [str(label) for label in self.urgency_clf.predict(features)],
        )

    def params(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "word_ngrams": list(cfg.word_ngrams),
            "char_ngrams": list(cfg.char_ngrams),
            "min_df": cfg.min_df,
            "class_weight": cfg.class_weight,
            "c_grid": list(cfg.c_grid),
            "chosen_c_topic": self.chosen_c.get("topic"),
            "chosen_c_urgency": self.chosen_c.get("urgency"),
            "vocabulary_size": self._vocabulary_size(),
        }

    def _vocabulary_size(self) -> int | None:
        if self.vectorizer is None:
            return None
        return sum(len(vec.vocabulary_) for _, vec in self.vectorizer.transformer_list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"vectorizer": self.vectorizer, "topic": self.topic_clf, "urgency": self.urgency_clf},
            path,
        )

    @classmethod
    def load(cls, path: Path, config: C1Config, seed: int) -> "TfidfLogReg":
        model = cls(config, seed)
        bundle = joblib.load(path)
        model.vectorizer, model.topic_clf, model.urgency_clf = (
            bundle["vectorizer"],
            bundle["topic"],
            bundle["urgency"],
        )
        return model
