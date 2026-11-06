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
from sklearn.pipeline import FeatureUnion

from customer_feedback_ai.models.base import LabeledTexts
from customer_feedback_ai.models.config import C1Config
from customer_feedback_ai.models.heads import fit_logreg_head, predict_labels


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
        common: dict[str, Any] = {
            "lowercase": True,
            "strip_accents": "unicode",
            "min_df": cfg.min_df,
            "sublinear_tf": True,
        }
        return FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
                        ngram_range=cfg.word_ngrams, max_features=cfg.max_features_word, **common
                    ),
                ),
                (
                    "char",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=cfg.char_ngrams,
                        max_features=cfg.max_features_char,
                        **common,
                    ),
                ),
            ]
        )

    def _fit_head(
        self, head: str, train_x: Any, train_y: Sequence[str], val_x: Any, val_y: Any
    ) -> Any:
        choice = fit_logreg_head(
            train_x,
            train_y,
            val_x,
            val_y,
            grid=self.config.c_grid,
            class_weight=self.config.class_weight,
            max_iter=self.config.max_iter,
            seed=self.seed,
        )
        self.chosen_c[head] = choice.c
        self.val_macro_f1[head] = choice.val_macro_f1
        return choice.classifier

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        self.vectorizer = self._vectorizer()
        train_x = self.vectorizer.fit_transform(train.texts)
        val_x = self.vectorizer.transform(val.texts) if val is not None and len(val) else None
        self.topic_clf = self._fit_head(
            "topic", train_x, train.topics, val_x, val.topics if val_x is not None and val else None
        )
        self.urgency_clf = self._fit_head(
            "urgency",
            train_x,
            train.urgencies,
            val_x,
            val.urgencies if val_x is not None and val else None,
        )

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        if self.vectorizer is None:
            msg = "fit the model before predicting"
            raise RuntimeError(msg)
        features = self.vectorizer.transform(list(texts))
        return predict_labels(self.topic_clf, features), predict_labels(self.urgency_clf, features)

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
            {
                "config": self.config.model_dump(mode="json"),
                "seed": self.seed,
                "vectorizer": self.vectorizer,
                "topic": self.topic_clf,
                "urgency": self.urgency_clf,
                "chosen_c": self.chosen_c,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "TfidfLogReg":
        bundle = joblib.load(path)
        model = cls(C1Config.model_validate(bundle["config"]), int(bundle["seed"]))
        model.vectorizer = bundle["vectorizer"]
        model.topic_clf, model.urgency_clf = bundle["topic"], bundle["urgency"]
        model.chosen_c = dict(bundle["chosen_c"])
        return model
