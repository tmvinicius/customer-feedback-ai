"""Blind annotation tool for the gold set (`make annotate`).

Shows one complaint at a time, with no company, no model output and, in the
re-annotation round, no previous label. Labels are written by the library to
`data/gold/annotation/labels.jsonl`.
"""

from datetime import UTC, datetime

import streamlit as st

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.labeling.config import load_labeling_config
from customer_feedback_ai.labeling.gold import (
    GOLD_SETS,
    GoldLabel,
    LabelStore,
    Round,
    load_queue,
    pending_items,
)
from customer_feedback_ai.labeling.taxonomy import load_taxonomy
from customer_feedback_ai.settings import Settings

ROUNDS: dict[str, Round] = {"Primeira anotação": "first", "Reanotação": "reannotation"}

st.set_page_config(page_title="Anotação do gold set", layout="centered")
st.title("Anotação do gold set")

settings = Settings()
paths = DataPaths(settings.data_dir)
if not paths.annotation_queue.exists():
    st.error("A fila de anotação não existe. Rode `make annotate` no terminal.")
    st.stop()

taxonomy = load_taxonomy()
gold_config = load_labeling_config().gold
items = load_queue(paths.annotation_queue)
store = LabelStore(paths.annotation_labels)
latest = store.latest()
now = datetime.now(UTC)

with st.sidebar:
    gold_set = st.radio("Conjunto", GOLD_SETS)
    round_ = ROUNDS[st.radio("Rodada", list(ROUNDS))]
    st.caption(f"Anotador: {settings.annotator_id}")
    for name in GOLD_SETS:
        in_set = [item for item in items if item.set == name]
        done = sum((item.item_id, "first") in latest for item in in_set)
        st.progress(done / len(in_set) if in_set else 0.0, text=f"{name}: {done}/{len(in_set)}")
    st.caption("Diretrizes: docs/annotation_guidelines.md")

pending = pending_items(items, latest, gold_set, round_, now, gold_config.reannotation_min_days)
if not pending:
    if round_ == "reannotation":
        st.info(
            "Nenhum item liberado para reanotação. Um item fica disponível "
            f"{gold_config.reannotation_min_days} dias depois da primeira anotação."
        )
    else:
        st.success(f"Todos os itens de {gold_set} foram anotados. Rode `make gold-report`.")
    st.stop()

item = pending[0]
st.caption(f"{gold_set} · item {item.position} · faltam {len(pending)}")
st.warning("Não copie o texto para fora desta ferramenta.", icon="🔒")
with st.container(border=True):
    st.text(item.text)

topic_descriptions = {topic.id: topic.description for topic in taxonomy.topics}
urgency_descriptions = {level.id: level.description for level in taxonomy.urgency}

with st.form(key=f"label-{item.item_id}-{round_}", clear_on_submit=True):
    topic = st.radio(
        "Tema do pedido principal",
        taxonomy.topic_ids,
        index=None,
        format_func=lambda t: f"{t}: {topic_descriptions[t]}",
    )
    urgency = st.radio(
        "Urgência",
        taxonomy.urgency_ids,
        index=None,
        format_func=lambda u: f"{u}: {urgency_descriptions[u]}",
        horizontal=False,
    )
    doubt = st.checkbox("Tenho dúvida neste item")
    note = st.text_input("Motivo da dúvida (opcional, sem copiar o texto)")
    submitted = st.form_submit_button("Salvar e ir para o próximo")

if submitted:
    if topic is None or urgency is None:
        st.error("Escolha um tema e uma urgência antes de salvar.")
    else:
        store.append(
            GoldLabel(
                item_id=item.item_id,
                set=item.set,
                round=round_,
                topic=topic,
                urgency=urgency,
                doubt=doubt,
                note=note.strip(),
                annotator=settings.annotator_id,
                annotated_at=datetime.now(UTC),
                taxonomy_version=taxonomy.version,
            )
        )
        st.rerun()
