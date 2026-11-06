"""C2 (Serafim + logistic regression) and C3 (BERT with two heads).

The tests build a tiny random BERT in a temporary folder, so they need no
download and no network. They run only where the optional PyTorch extra is
installed (`make setup DEEP=1`); CI skips them.
"""

from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("sentence_transformers")

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.evaluation.metrics import macro_f1
from customer_feedback_ai.labeling.gold import GOLD_DEV
from customer_feedback_ai.labeling.taxonomy import Taxonomy, load_taxonomy
from customer_feedback_ai.llm.fake import FakeLLM
from customer_feedback_ai.models.base import LabeledTexts
from customer_feedback_ai.models.bert import BertTwoHeads, balanced_weights
from customer_feedback_ai.models.config import C2Config, C3Config, MeasurementConfig, TrainConfig
from customer_feedback_ai.models.embeddings import SerafimLogReg
from customer_feedback_ai.models.measure import profile_in_subprocess
from customer_feedback_ai.models.registry import load_model
from customer_feedback_ai.pipelines import train_local

from .conftest import REPO_ROOT
from .test_gold import label_all
from .test_silver import run as run_silver

WORDS = {
    "cancelamento": ("quero cancelar o plano", "pedi o cancelamento da assinatura"),
    "entrega_atraso": ("o pedido nao chegou", "entrega atrasada ha semanas"),
    "reembolso_estorno": ("quero meu dinheiro de volta", "o estorno nao caiu"),
}
URGENCY = {"cancelamento": "baixa", "entrega_atraso": "media", "reembolso_estorno": "alta"}


def separable(repeats: int, offset: int = 0) -> LabeledTexts:
    rows = [
        (f"{phrase} protocolo {n + offset}", topic, URGENCY[topic])
        for n in range(repeats)
        for topic, phrases in WORDS.items()
        for phrase in phrases
    ]
    return LabeledTexts(
        tuple(f"id{n}" for n in range(len(rows))),
        tuple(r[0] for r in rows),
        tuple(r[1] for r in rows),
        tuple(r[2] for r in rows),
    )


@pytest.fixture(scope="module")
def tiny_bert(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A one-layer BERT with a WordPiece vocabulary of the test words and characters."""
    import torch
    from transformers import BertConfig, BertModel, BertTokenizerFast

    folder = tmp_path_factory.mktemp("tiny_bert")
    words = sorted({w for phrases in WORDS.values() for p in phrases for w in p.split()})
    chars = list("abcdefghijklmnopqrstuvwxyz0123456789")
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", *words, *chars]
    vocab += [f"##{c}" for c in chars]
    tokenizer = BertTokenizerFast(vocab={t: i for i, t in enumerate(vocab)}, do_lower_case=True)
    assert "[UNK]" not in tokenizer.tokenize("quero cancelar o plano protocolo 7")
    config = BertConfig(
        vocab_size=len(vocab),
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=64,
    )
    torch.manual_seed(0)
    BertModel(config).save_pretrained(folder)
    tokenizer.save_pretrained(folder)
    return folder


def c3_config(tiny_bert: Path, **overrides: object) -> C3Config:
    values: dict[str, object] = {
        "encoder": str(tiny_bert),
        "max_length": 16,
        "batch_size": 4,
        "eval_batch_size": 8,
        "learning_rate": 5e-3,
        "warmup_ratio": 0.0,
        "epochs": 12,
        "patience": 12,
        "device": "cpu",
    }
    return C3Config.model_validate(values | overrides)


# --- C2 ------------------------------------------------------------------------------


def test_c2_trains_on_embeddings_and_round_trips(tiny_bert: Path, tmp_path: Path) -> None:
    config = C2Config(encoder=str(tiny_bert), c_grid=(1.0, 100.0), max_iter=500)
    model = SerafimLogReg(config, seed=1)
    train, val = separable(4), separable(2, offset=50)
    model.fit(train, val)
    topics, urgencies = model.predict(val.texts)
    assert len(topics) == len(urgencies) == len(val)
    params = model.params()
    assert params["dimensions"] == 32
    assert params["chosen_c_topic"] in config.c_grid
    assert params["truncated_train"] == 0
    assert params["truncated_train_total"] == len(train)

    model.save(tmp_path / "c2")
    assert (tmp_path / "c2" / "encoder").is_dir()
    again = load_model("c2", tmp_path / "c2")
    assert again.predict(val.texts) == (topics, urgencies)


# --- C3 ------------------------------------------------------------------------------


def test_balanced_weights_follow_scikit_learn() -> None:
    weights = balanced_weights([0, 0, 0, 1], 2).tolist()
    assert weights == pytest.approx([4 / 6, 2.0])


def test_c3_learns_counts_truncation_and_round_trips(tiny_bert: Path, tmp_path: Path) -> None:
    # Normal texts have about 17 tokens ("protocolo" is not in the tiny vocabulary).
    model = BertTwoHeads(c3_config(tiny_bert, max_length=48), seed=1)
    train = separable(3)
    val = separable(1, offset=90)
    long_text = " ".join(["protocolo"] * 30)
    train_with_long = LabeledTexts(
        (*train.item_ids, "long"),
        (*train.texts, long_text),
        (*train.topics, "cancelamento"),
        (*train.urgencies, "baixa"),
    )
    model.fit(train_with_long, val)

    topics, _ = model.predict(train.texts)
    assert macro_f1(train.topics, topics) == 1.0
    params = model.params()
    assert params["truncated_train"] == 1
    assert params["truncated_train_total"] == len(train) + 1
    assert params["device"] == "cpu"
    scores = [h["val_topic_macro_f1"] for h in params["history"]]
    assert scores[params["best_epoch"] - 1] == max(scores)

    model.save(tmp_path / "c3")
    again = load_model("c3", tmp_path / "c3")
    assert again.predict(val.texts) == model.predict(val.texts)


def test_c3_stops_early_without_improvement(tiny_bert: Path) -> None:
    model = BertTwoHeads(c3_config(tiny_bert, epochs=30, patience=0), seed=1)
    model.fit(separable(2), separable(1, offset=70))
    info = model.params()
    assert info["epochs_run"] < 30
    assert info["epochs_run"] == info["best_epoch"] + 1


def test_c3_inference_is_profiled_on_cpu(tiny_bert: Path, tmp_path: Path) -> None:
    model = BertTwoHeads(c3_config(tiny_bert, epochs=1), seed=1)
    model.fit(separable(1), None)
    model.save(tmp_path / "c3")
    profile = profile_in_subprocess("c3", tmp_path / "c3", ["quero cancelar"] * 3, tmp_path)
    assert profile.calls == 3
    assert profile.latency_p50_s is not None


# --- pipeline -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


def test_train_local_runs_c2_and_c3(
    labeling_paths: DataPaths, taxonomy: Taxonomy, tiny_bert: Path
) -> None:
    run_silver(labeling_paths, taxonomy, FakeLLM())
    label_all(labeling_paths, taxonomy, GOLD_DEV)
    config = TrainConfig(
        c2=C2Config(encoder=str(tiny_bert), c_grid=(1.0,), max_iter=300),
        c3=c3_config(tiny_bert, epochs=1, max_length=32),
        measurement=MeasurementConfig(latency_samples=5),
    )
    from customer_feedback_ai.models.config import load_rules

    report = train_local.run(
        labeling_paths,
        config,
        load_rules(),
        taxonomy,
        models=["c2", "c3"],
        allow_fake_labels=True,
        train_size=60,
        track=False,
    )
    assert set(report["models"]) == {"c2", "c3"}
    assert report["tuned_on_silver_val"] == ["c2", "c3"]
    for name, result in report["models"].items():
        assert result["gold_dev"]["n"] > 0, name
        assert result["cost"]["calls"] == 5
        assert result["cost"]["artifact_bytes"] > 0
    c3 = report["models"]["c3"]["params"]
    assert c3["max_length"] == 32
    assert 0 <= c3["truncated_share_train"] <= 1
