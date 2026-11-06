"""Names, artifacts and constructors of the local models.

Imports are lazy, so loading B0 never imports scikit-learn and loading C1 never
imports PyTorch. The inference probe relies on this to measure each model's own
memory, libraries included.
"""

from pathlib import Path

from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.models.base import TopicUrgencyModel
from customer_feedback_ai.models.config import RulesConfig, TrainConfig

MODELS = ("b0", "b1", "c1", "c2", "c3")
DEEP_MODELS = frozenset({"c2", "c3"})
ARTIFACT_NAMES = {"b0": "b0.json", "b1": "b1.json", "c1": "c1.joblib", "c2": "c2", "c3": "c3"}
DEEP_HINT = (
    "C2 and C3 need PyTorch, Transformers and Sentence Transformers: run `make setup DEEP=1`, "
    'or train only the other models with MODELS="b0 b1 c1"'
)


def _check(name: str) -> None:
    if name not in MODELS:
        msg = f"unknown model {name!r}; choose from {list(MODELS)}"
        raise DataPipelineError(msg)


def deep_available() -> bool:
    from importlib.util import find_spec

    return all(find_spec(m) is not None for m in ("torch", "transformers", "sentence_transformers"))


def require_deep(names: list[str]) -> None:
    if DEEP_MODELS & set(names) and not deep_available():
        raise DataPipelineError(DEEP_HINT)


def build_model(name: str, rules: RulesConfig, config: TrainConfig) -> TopicUrgencyModel:
    _check(name)
    if name == "b0":
        from customer_feedback_ai.models.baselines import MajorityBaseline

        return MajorityBaseline()
    if name == "b1":
        from customer_feedback_ai.models.baselines import KeywordRules

        return KeywordRules(rules)
    if name == "c1":
        from customer_feedback_ai.models.tfidf import TfidfLogReg

        return TfidfLogReg(config.c1, config.seed)
    if name == "c2":
        from customer_feedback_ai.models.embeddings import SerafimLogReg

        return SerafimLogReg(config.c2, config.seed)
    from customer_feedback_ai.models.bert import BertTwoHeads

    return BertTwoHeads(config.c3, config.seed)


def load_model(name: str, artifact: Path) -> TopicUrgencyModel:
    _check(name)
    if name == "b0":
        from customer_feedback_ai.models.baselines import MajorityBaseline

        return MajorityBaseline.load(artifact)
    if name == "b1":
        from customer_feedback_ai.models.baselines import KeywordRules

        return KeywordRules.load(artifact)
    if name == "c1":
        from customer_feedback_ai.models.tfidf import TfidfLogReg

        return TfidfLogReg.load(artifact)
    if name == "c2":
        from customer_feedback_ai.models.embeddings import SerafimLogReg

        return SerafimLogReg.load(artifact)
    from customer_feedback_ai.models.bert import BertTwoHeads

    return BertTwoHeads.load(artifact)
