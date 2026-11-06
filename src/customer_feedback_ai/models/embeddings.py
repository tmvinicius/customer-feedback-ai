"""C2: Serafim sentence embeddings + logistic regression (AGENTS.md, section 8).

The encoder is used as is, without fine-tuning: the question C2 answers is
whether ready-made embeddings are worth the dependency. Two classifiers, topic
and urgency, sit on the same embeddings, with C chosen on `silver_val`.

The saved model is self-contained: the encoder weights are copied next to the
classifiers, so loading it needs no download.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import joblib
import numpy as np

from customer_feedback_ai.models.base import LabeledTexts
from customer_feedback_ai.models.config import C2Config
from customer_feedback_ai.models.heads import fit_logreg_head, predict_labels


def quiet_hf() -> None:
    """No download progress bars or advisory warnings in the pipeline logs."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import logging

    from transformers.utils import logging as hf_logging

    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

    hf_logging.set_verbosity_error()
    hf_logging.disable_progress_bar()


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...

    def info(self) -> dict[str, Any]: ...

    def truncated(self, texts: Sequence[str]) -> int: ...

    def save(self, path: Path) -> None: ...


class SentenceEncoder:
    """A Sentence Transformers model on CPU (inference is compared on CPU)."""

    def __init__(self, source: str, revision: str | None, batch_size: int, normalize: bool):
        quiet_hf()
        from sentence_transformers import SentenceTransformer

        self.source = source
        self.revision = revision
        self.batch_size = batch_size
        self.normalize = normalize
        self.model = SentenceTransformer(source, revision=revision, device="cpu")

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def truncated(self, texts: Sequence[str]) -> int:
        """Texts longer than the encoder's limit, which it silently cuts."""
        limit = self.model.max_seq_length
        lengths = self.model.tokenizer(list(texts), add_special_tokens=True)["input_ids"]
        return sum(len(ids) > limit for ids in lengths)

    def info(self) -> dict[str, Any]:
        backbone = getattr(self.model[0], "auto_model", None)
        config = getattr(backbone, "config", None)
        return {
            "encoder": self.source,
            "encoder_revision": self.revision,
            "encoder_commit": getattr(config, "_commit_hash", None),
            "max_seq_length": self.model.max_seq_length,
            "dimensions": self.model.get_embedding_dimension(),
        }

    def save(self, path: Path) -> None:
        self.model.save(str(path))


class SerafimLogReg:
    name = "c2"

    def __init__(self, config: C2Config, seed: int, encoder: Encoder | None = None):
        self.config = config
        self.seed = seed
        self.encoder = encoder
        self.topic_clf: Any = None
        self.urgency_clf: Any = None
        self.chosen_c: dict[str, float | None] = {}
        self.encoder_info: dict[str, Any] = {}
        self.truncation: dict[str, int] = {}

    def _encoder(self) -> Encoder:
        if self.encoder is None:
            cfg = self.config
            self.encoder = SentenceEncoder(cfg.encoder, cfg.revision, cfg.batch_size, cfg.normalize)
        return self.encoder

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        encoder = self._encoder()
        self.encoder_info = encoder.info()
        train_x = encoder.encode(train.texts)
        has_val = val is not None and len(val) > 0
        val_x = encoder.encode(val.texts) if has_val and val is not None else None
        self.truncation = {"train": encoder.truncated(train.texts), "train_total": len(train)}
        if has_val and val is not None:
            self.truncation |= {"val": encoder.truncated(val.texts), "val_total": len(val)}
        for head, train_y, val_y in (
            ("topic", train.topics, val.topics if has_val and val else None),
            ("urgency", train.urgencies, val.urgencies if has_val and val else None),
        ):
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
            setattr(self, f"{head}_clf", choice.classifier)

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        if self.topic_clf is None:
            msg = "fit the model before predicting"
            raise RuntimeError(msg)
        features = self._encoder().encode(texts)
        return predict_labels(self.topic_clf, features), predict_labels(self.urgency_clf, features)

    def params(self) -> dict[str, Any]:
        cfg = self.config
        return {
            **self.encoder_info,
            "normalize": cfg.normalize,
            "class_weight": cfg.class_weight,
            "c_grid": list(cfg.c_grid),
            "chosen_c_topic": self.chosen_c.get("topic"),
            "chosen_c_urgency": self.chosen_c.get("urgency"),
            **{f"truncated_{k}": v for k, v in self.truncation.items()},
        }

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._encoder().save(path / "encoder")
        joblib.dump(
            {
                "config": self.config.model_dump(mode="json"),
                "seed": self.seed,
                "topic": self.topic_clf,
                "urgency": self.urgency_clf,
                "chosen_c": self.chosen_c,
                "encoder_info": self.encoder_info,
            },
            path / "heads.joblib",
        )

    @classmethod
    def load(cls, path: Path, encoder: Encoder | None = None) -> "SerafimLogReg":
        bundle = joblib.load(path / "heads.joblib")
        config = C2Config.model_validate(bundle["config"])
        if encoder is None:
            encoder = SentenceEncoder(
                str(path / "encoder"), None, config.batch_size, config.normalize
            )
        model = cls(config, int(bundle["seed"]), encoder)
        model.topic_clf, model.urgency_clf = bundle["topic"], bundle["urgency"]
        model.chosen_c = dict(bundle["chosen_c"])
        model.encoder_info = dict(bundle["encoder_info"])
        return model
