"""The annotation tool shows one complaint, hides the company and saves a human label."""

import pytest
from streamlit.testing.v1 import AppTest

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.labeling.gold import GOLD_DEV, LabelStore, load_queue

from .conftest import REPO_ROOT

APP = str(REPO_ROOT / "ui" / "annotate.py")


@pytest.fixture
def app(labeling_paths: DataPaths, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("DATA_DIR", str(labeling_paths.root))
    monkeypatch.setenv("ANNOTATOR_ID", "pessoa_teste")
    monkeypatch.chdir(REPO_ROOT)
    return AppTest.from_file(APP, default_timeout=60)


def test_shows_the_first_pending_complaint(app: AppTest, labeling_paths: DataPaths) -> None:
    app.run()
    first = next(i for i in load_queue(labeling_paths.annotation_queue) if i.set == GOLD_DEV)

    assert not app.exception
    assert first.text in [element.value for element in app.text]
    assert all("empresa" not in str(caption.value).lower() for caption in app.caption)


def test_saves_a_label_and_moves_on(app: AppTest, labeling_paths: DataPaths) -> None:
    app.run()
    first = next(i for i in load_queue(labeling_paths.annotation_queue) if i.set == GOLD_DEV)
    radios = {radio.label: radio for radio in app.radio}
    radios["Tema do pedido principal"].set_value("cancelamento")
    radios["Urgência"].set_value("alta")
    app.button[0].click().run()

    labels = LabelStore(labeling_paths.annotation_labels).all()
    assert not app.exception
    assert len(labels) == 1
    assert (labels[0].item_id, labels[0].topic, labels[0].urgency) == (
        first.item_id,
        "cancelamento",
        "alta",
    )
    assert labels[0].annotator == "pessoa_teste"
    assert labels[0].round == "first"
    assert first.text not in [element.value for element in app.text]


def test_refuses_to_save_without_both_labels(app: AppTest, labeling_paths: DataPaths) -> None:
    app.run()
    app.button[0].click().run()
    assert LabelStore(labeling_paths.annotation_labels).all() == []
    assert any("Escolha um tema" in str(error.value) for error in app.error)


def test_asks_to_build_the_queue_first(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(REPO_ROOT)
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert any("make annotate" in str(error.value) for error in app.error)
