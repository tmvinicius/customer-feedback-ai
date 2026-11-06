"""Local models B0, B1 and C1, their measurements and `make train-local`. Synthetic data only.

C2 and C3 (PyTorch) are tested in test_deep_models.py.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from customer_feedback_ai.data.duck import connect
from customer_feedback_ai.data.manifest import read_manifest
from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.data.schema import TEXT_COLUMN
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.evaluation.classification import evaluate
from customer_feedback_ai.evaluation.metrics import macro_f1, recall_of
from customer_feedback_ai.evaluation.tracking import flatten_metrics
from customer_feedback_ai.labeling.gold import GOLD_DEV
from customer_feedback_ai.labeling.silver import SILVER_TRAIN
from customer_feedback_ai.labeling.taxonomy import Taxonomy, load_taxonomy
from customer_feedback_ai.llm.fake import FakeLLM
from customer_feedback_ai.models import registry
from customer_feedback_ai.models.base import LabeledTexts, fold
from customer_feedback_ai.models.baselines import KeywordRules, MajorityBaseline, keyword_pattern
from customer_feedback_ai.models.config import (
    C1Config,
    MeasurementConfig,
    RulesConfig,
    TopicRule,
    TrainConfig,
    UrgencyRules,
    load_rules,
    load_train_config,
)
from customer_feedback_ai.models.dataset import INPUT_COLUMNS, load_silver
from customer_feedback_ai.models.measure import (
    InferenceProfile,
    artifact_bytes,
    profile_in_subprocess,
    rss_method,
    run_per_item,
)
from customer_feedback_ai.models.tfidf import TfidfLogReg
from customer_feedback_ai.pipelines import train_local

from .conftest import REPO_ROOT
from .test_gold import label_all
from .test_silver import run as run_silver


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


def labeled(rows: list[tuple[str, str, str]]) -> LabeledTexts:
    return LabeledTexts(
        tuple(f"id{n}" for n in range(len(rows))),
        tuple(r[0] for r in rows),
        tuple(r[1] for r in rows),
        tuple(r[2] for r in rows),
    )


RULES = RulesConfig(
    version="test",
    fallback_topic="outro",
    topics=(
        TopicRule(id="fraude_golpe", keywords=("golpe",)),
        TopicRule(id="cancelamento", keywords=("cancelar", "cancelamento")),
    ),
    urgency=UrgencyRules(default="media", alta=("urgente",), baixa=("sugestão",)),
)


# --- B0 and B1 ---------------------------------------------------------------------


def test_majority_breaks_ties_by_label_order() -> None:
    model = MajorityBaseline()
    model.fit(labeled([("a", "reembolso_estorno", "alta"), ("b", "cancelamento", "baixa")]))
    assert model.predict(["x", "y"]) == (["cancelamento"] * 2, ["alta"] * 2)


def test_majority_needs_fit() -> None:
    with pytest.raises(RuntimeError):
        MajorityBaseline().predict(["x"])


def test_rules_ignore_case_and_accents_and_first_rule_wins() -> None:
    rules = KeywordRules(RULES)
    assert rules.predict_one("Quero CANCELAR, foi um golpe!") == ("fraude_golpe", "media")
    assert rules.predict_one("Cancelamento URGENTE") == ("cancelamento", "alta")
    assert rules.predict_one("Uma sugestao de melhoria") == ("outro", "baixa")
    assert fold("  Açúcar   É  ") == "acucar e"


def test_keywords_match_whole_words_unless_they_are_stems() -> None:
    whole = keyword_pattern(["uti", "sac"])
    assert whole.search(fold("Minha mãe está na UTI."))
    assert not whole.search(fold("Utilizei o cupom"))
    assert not whole.search(fold("Fiz uma transação e fui sacar"))
    stem = keyword_pattern(["negativ*"])
    assert stem.search(fold("Fui negativado"))
    assert not stem.search(fold("resultado positivo e renegativo"))


def test_invalid_keywords_are_rejected() -> None:
    with pytest.raises(ValueError, match="invalid keyword"):
        TopicRule(id="x", keywords=("a*b",))
    with pytest.raises(ValueError, match="invalid keyword"):
        UrgencyRules(alta=("*",))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Utilizei o cupom e não deu desconto", ("outro", "media")),
        ("Fiz uma transação pelo app e sumiu", ("outro", "media")),
        ("Péssimo tratamento do atendente", ("atendimento", "media")),
        ("O produto foi entregue com defeito", ("produto_defeito", "media")),
        ("Meu endereço está errado no pedido", ("outro", "media")),
        ("Cobrança indevida no cartão de crédito", ("cobranca_indevida", "media")),
        ("Estou sem internet há três dias", ("servico_indisponivel", "alta")),
        ("Minha mãe está na UTI e o plano negou", ("outro", "alta")),
    ],
)
def test_project_rules_avoid_known_false_matches(text: str, expected: tuple[str, str]) -> None:
    assert KeywordRules(load_rules()).predict_one(text) == expected


def test_rules_and_majority_round_trip(tmp_path: Path) -> None:
    rules = KeywordRules(RULES)
    rules.save(tmp_path / "b1.json")
    assert KeywordRules.load(tmp_path / "b1.json").predict(["golpe"]) == rules.predict(["golpe"])
    majority = MajorityBaseline()
    majority.fit(labeled([("a", "outro", "baixa")]))
    majority.save(tmp_path / "b0.json")
    assert MajorityBaseline.load(tmp_path / "b0.json").predict(["x"]) == (["outro"], ["baixa"])


def test_rules_file_only_uses_taxonomy_topics(taxonomy: Taxonomy) -> None:
    train_local.check_rules(load_rules(), taxonomy)
    bad = RULES.model_copy(update={"fallback_topic": "inexistente"})
    with pytest.raises(DataPipelineError, match="inexistente"):
        train_local.check_rules(bad, taxonomy)


# --- C1 ----------------------------------------------------------------------------

WORDS = {
    "cancelamento": ("quero cancelar o plano", "pedi o cancelamento da assinatura"),
    "entrega_atraso": ("o pedido não chegou", "entrega atrasada há semanas"),
    "reembolso_estorno": ("quero meu dinheiro de volta", "o estorno não caiu"),
}
URGENCY = {"cancelamento": "baixa", "entrega_atraso": "media", "reembolso_estorno": "alta"}
SMALL_C1 = C1Config(min_df=1, c_grid=(0.25, 4.0), max_iter=500)


def separable(repeats: int, offset: int = 0) -> LabeledTexts:
    rows = [
        (f"{phrase} protocolo {n + offset}", topic, URGENCY[topic])
        for n in range(repeats)
        for topic, phrases in WORDS.items()
        for phrase in phrases
    ]
    return labeled(rows)


def test_c1_learns_separable_texts_and_round_trips(tmp_path: Path) -> None:
    model = TfidfLogReg(SMALL_C1, seed=1)
    train, val = separable(5), separable(2, offset=100)
    model.fit(train, val)
    topics, urgencies = model.predict(val.texts)
    assert macro_f1(val.topics, topics) == 1.0
    assert list(urgencies) == list(val.urgencies)
    params = model.params()
    assert params["chosen_c_topic"] in SMALL_C1.c_grid
    assert params["vocabulary_size"] > 0
    model.save(tmp_path / "c1.joblib")
    again = TfidfLogReg.load(tmp_path / "c1.joblib")
    assert again.predict(val.texts) == (topics, urgencies)


def test_c1_with_one_urgency_class_predicts_it() -> None:
    base = separable(3)
    data = labeled(
        [(text, topic, "media") for text, topic in zip(base.texts, base.topics, strict=True)]
    )
    model = TfidfLogReg(SMALL_C1, seed=1)
    model.fit(data, None)
    assert set(model.predict(["entrega atrasada"])[1]) == {"media"}
    assert model.params()["chosen_c_urgency"] is None


# --- evaluation and measurement ------------------------------------------------------


def test_evaluate_reports_main_metric_support_and_high_recall() -> None:
    gold_t = ["a", "a", "b", "b"]
    pred_t = ["a", "b", "b", "b"]
    gold_u = ["alta", "alta", "media", "baixa"]
    pred_u = ["alta", "media", "media", "baixa"]
    result = evaluate(gold_t, pred_t, gold_u, pred_u, resamples=50, seed=1)
    assert result["n"] == 4
    assert result["topic_macro_f1"]["value"] == pytest.approx(macro_f1(gold_t, pred_t))
    assert result["topic_macro_f1"]["ci_low"] <= result["topic_macro_f1"]["value"]
    assert result["topic_per_class"]["b"]["support"] == 2
    high = result["high_urgency_recall"]
    assert high == {"value": recall_of(gold_u, pred_u, "alta"), "support": 2}


def test_flatten_metrics_keeps_only_numbers() -> None:
    flat = flatten_metrics({"a": {"b": 1, "c": None, "d": "x", "e": True}, "f": 0.5})
    assert flat == {"a.b": 1.0, "f": 0.5}


def test_latency_is_measured_per_complaint_after_a_warm_up() -> None:
    ticks = iter(float(n) for n in range(100))
    cpu = iter([0.0, 0.3])
    calls: list[list[str]] = []
    run = run_per_item(
        lambda texts: calls.append(list(texts)),
        ["x", "y", "z"],
        clock=lambda: next(ticks),
        cpu_clock=lambda: next(cpu),
    )
    assert calls == [["x"], ["x"], ["y"], ["z"]]
    profile = InferenceProfile.from_run(run, load_seconds=0.5, before=100, peak=250)
    assert (profile.calls, profile.latency_p50_s) == (3, 1.0)
    assert profile.cpu_seconds_per_1000 == pytest.approx(100.0)
    assert profile.model_rss_bytes == 150
    assert run_per_item(lambda texts: None, []).durations == ()


def test_inference_is_profiled_in_a_fresh_process(tmp_path: Path) -> None:
    model = MajorityBaseline()
    model.fit(labeled([("a", "outro", "media")]))
    model.save(tmp_path / "b0.json")
    profile = profile_in_subprocess("b0", tmp_path / "b0.json", ["x", "y"], tmp_path / "work")
    assert profile.calls == 2
    assert profile.peak_rss_bytes is None or profile.peak_rss_bytes > 0
    assert list((tmp_path / "work").iterdir()) == []  # the texts file is removed
    with pytest.raises(DataPipelineError, match="probe for b0 failed"):
        profile_in_subprocess("b0", tmp_path / "missing.json", ["x"], tmp_path / "work")


@pytest.mark.skipif(rss_method() != "VmHWM", reason="Linux high-water mark only")
def test_probe_memory_does_not_inherit_the_parent_peak(tmp_path: Path) -> None:
    model = MajorityBaseline()
    model.fit(labeled([("a", "outro", "media")]))
    model.save(tmp_path / "b0.json")
    ballast = bytearray(400 * 2**20)  # raises this process's peak by 400 MB
    ballast[::4096] = b"x" * len(ballast[::4096])
    profile = profile_in_subprocess("b0", tmp_path / "b0.json", ["x"], tmp_path)
    assert profile.peak_rss_bytes is not None
    assert profile.peak_rss_bytes < 300 * 2**20
    assert profile.model_rss_bytes is not None
    del ballast


def test_artifact_size_covers_folders(tmp_path: Path) -> None:
    (tmp_path / "m" / "sub").mkdir(parents=True)
    (tmp_path / "m" / "a.bin").write_bytes(b"12345")
    (tmp_path / "m" / "sub" / "b.bin").write_bytes(b"123")
    assert artifact_bytes(tmp_path / "m") == 8
    assert artifact_bytes(tmp_path / "m" / "a.bin") == 5


# --- data and pipeline ---------------------------------------------------------------


def test_classifiers_read_only_the_complaint_text() -> None:
    assert INPUT_COLUMNS == (TEXT_COLUMN,)


def test_unknown_models_fail_clearly() -> None:
    with pytest.raises(DataPipelineError, match="unknown"):
        registry.build_model("zz", RULES, TrainConfig())


def test_deep_models_without_pytorch_say_how_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "deep_available", lambda: False)
    with pytest.raises(DataPipelineError, match="make setup DEEP=1"):
        registry.require_deep(["b0", "c3"])
    registry.require_deep(["b0", "c1"])


def test_train_config_file_is_valid() -> None:
    config = load_train_config()
    assert config.measurement.latency_samples >= 200
    assert config.measurement.bootstrap_resamples == 1000


@pytest.fixture
def silver_paths(labeling_paths: DataPaths, taxonomy: Taxonomy) -> DataPaths:
    run_silver(labeling_paths, taxonomy, FakeLLM())
    return labeling_paths


def test_fake_labels_are_refused_without_the_flag(
    silver_paths: DataPaths, taxonomy: Taxonomy
) -> None:
    con = connect(silver_paths.tmp_dir)
    with pytest.raises(DataPipelineError, match="FakeLLM"):
        load_silver(con, silver_paths, SILVER_TRAIN)
    with pytest.raises(DataPipelineError, match="FakeLLM"):
        train_local.run(
            silver_paths, TrainConfig(), load_rules(), taxonomy, models=["b0"], track=False
        )


def test_train_local_trial_run_end_to_end(silver_paths: DataPaths, taxonomy: Taxonomy) -> None:
    label_all(silver_paths, taxonomy, GOLD_DEV)
    config = TrainConfig(
        c1=C1Config(min_df=1, c_grid=(1.0,), max_iter=300),
        measurement=MeasurementConfig(latency_samples=20),
    )
    report = train_local.run(
        silver_paths,
        config,
        load_rules(),
        taxonomy,
        models=["b0", "b1", "c1"],
        allow_fake_labels=True,
        train_size=150,
    )
    assert report["valid"] is False
    assert report["label_backends"] == ["fake"]
    assert report["counts"]["train_labels"] == 150
    assert report["counts"]["gold_dev_labeled"] == report["counts"]["gold_dev_queue"] > 0
    assert set(report["models"]) == {"b0", "b1", "c1"}
    assert report["comparison_set"] == "gold_dev"
    assert report["tuned_on_silver_val"] == ["c1"]
    assert report["machine"]["cpu_count"]
    for name, result in report["models"].items():
        assert (silver_paths.root / result["artifact"]).exists(), name
        assert result["gold_dev"]["n"] == report["counts"]["gold_dev_labeled"]
        assert result["cost"]["calls"] == 20
        assert result["cost"]["load_seconds"] >= 0
        assert result["cost"]["artifact_bytes"] > 0
        assert result["mlflow_run_id"]

    saved = json.loads((silver_paths.reports_dir / "train_local.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == report["run_id"]
    manifest = read_manifest(silver_paths.manifest("train_local"))
    assert manifest.details["valid"] is False
    assert manifest.counts["train_labels"] == 150

    db = sqlite3.connect(silver_paths.mlflow_dir / "mlflow.db")
    tags = db.execute("SELECT value FROM tags WHERE key = 'valid'").fetchall()
    assert tags == [("false",)] * 3
    (location,) = db.execute(
        "SELECT artifact_location FROM experiments WHERE name = 'customer-feedback-ai'"
    ).fetchone()
    assert location == (silver_paths.mlflow_dir / "artifacts").resolve().as_uri()
    query = "SELECT key, value FROM params WHERE key = 'input_columns'"
    params = dict(db.execute(query).fetchall())
    assert params == {"input_columns": TEXT_COLUMN}


def test_train_size_cannot_exceed_the_silver(silver_paths: DataPaths, taxonomy: Taxonomy) -> None:
    with pytest.raises(DataPipelineError, match="larger"):
        train_local.run(
            silver_paths,
            TrainConfig(),
            load_rules(),
            taxonomy,
            models=["b0"],
            allow_fake_labels=True,
            train_size=10**6,
            track=False,
        )
