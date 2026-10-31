"""The taxonomy config loads, matches the plan in AGENTS.md and rejects invalid shapes."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from customer_feedback_ai.labeling.taxonomy import Label, Taxonomy, load_taxonomy

TAXONOMY_YAML = Path(__file__).resolve().parents[2] / "configs" / "taxonomy.yaml"


def test_taxonomy_matches_the_plan() -> None:
    taxonomy = load_taxonomy(TAXONOMY_YAML)
    assert taxonomy.topic_ids == (
        "cobranca_indevida",
        "cancelamento",
        "reembolso_estorno",
        "entrega_atraso",
        "produto_defeito",
        "servico_indisponivel",
        "fraude_golpe",
        "oferta_contrato",
        "atendimento",
        "dados_cadastro",
        "credito_negativacao",
        "outro",
    )
    assert taxonomy.urgency_ids == ("baixa", "media", "alta")


def _taxonomy(topics: list[str], urgency: list[str]) -> Taxonomy:
    return Taxonomy(
        version="test",
        topics=tuple(Label(id=t, description="x") for t in topics),
        urgency=tuple(Label(id=u, description="x") for u in urgency),
    )


@pytest.mark.parametrize(
    ("topics", "urgency"),
    [
        (["cancelamento"], ["baixa", "media", "alta"]),  # no fallback topic
        (["outro", "outro"], ["baixa", "media", "alta"]),  # duplicate topic
        (["outro"], ["alta", "media", "baixa"]),  # wrong order
        (["outro"], ["baixa", "alta"]),  # missing level
    ],
)
def test_invalid_taxonomies_are_rejected(topics: list[str], urgency: list[str]) -> None:
    with pytest.raises(ValidationError):
        _taxonomy(topics, urgency)
