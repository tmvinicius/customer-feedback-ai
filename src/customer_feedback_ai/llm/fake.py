"""Deterministic offline LLM for tests and synthetic dry runs.

It labels by simple keyword rules, so its labels mean nothing as a model and
must never be reported as results. `invalid_first_every` makes some requests
return broken JSON on the first attempt, to exercise the retry path.
"""

import hashlib
import json
import unicodedata
from collections.abc import Iterator, Sequence

from customer_feedback_ai.llm.types import LLMRequest, LLMResult, TokenUsage

_TOPIC_RULES: tuple[tuple[str, str], ...] = (
    ("nao reconheco", "fraude_golpe"),
    ("nao fiz", "fraude_golpe"),
    ("golpe", "fraude_golpe"),
    ("negativ", "credito_negativacao"),
    ("emprestimo", "credito_negativacao"),
    ("cancel", "cancelamento"),
    ("estorno", "reembolso_estorno"),
    ("reembolso", "reembolso_estorno"),
    ("entrega", "entrega_atraso"),
    ("rastreio", "entrega_atraso"),
    ("quebrado", "produto_defeito"),
    ("defeito", "produto_defeito"),
    ("internet", "servico_indisponivel"),
    ("energia", "servico_indisponivel"),
    ("cobr", "cobranca_indevida"),
    ("atendente", "atendimento"),
    ("cadastro", "dados_cadastro"),
    ("anuncio", "oferta_contrato"),
)
_HIGH_URGENCY = ("oxigenio", "urgencia", "boletim de ocorrencia", "sem internet", "cortada")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fake_label(text: str) -> dict[str, str]:
    folded = _fold(text)
    topic = next((topic for key, topic in _TOPIC_RULES if key in folded), "outro")
    if any(key in folded for key in _HIGH_URGENCY):
        urgency = "alta"
    elif topic in ("outro", "atendimento"):
        urgency = "baixa"
    else:
        urgency = "media"
    return {"topic": topic, "urgency": urgency}


class FakeLLM:
    """In-memory `BatchLLMClient`. Batches end as soon as they are submitted."""

    def __init__(self, invalid_first_every: int = 0):
        self.invalid_first_every = invalid_first_every
        self.batches: dict[str, list[LLMRequest]] = {}
        self._attempts: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "fake"

    @property
    def is_external(self) -> bool:
        return False

    def submit_batch(self, requests: Sequence[LLMRequest]) -> str:
        batch_id = f"fake-batch-{len(self.batches) + 1}"
        self.batches[batch_id] = list(requests)
        return batch_id

    def batch_ended(self, batch_id: str) -> bool:
        return batch_id in self.batches

    def batch_results(self, batch_id: str) -> Iterator[LLMResult]:
        for request in self.batches[batch_id]:
            yield self._answer(request)

    def _answer(self, request: LLMRequest) -> LLMResult:
        attempt = self._attempts.get(request.custom_id, 0) + 1
        self._attempts[request.custom_id] = attempt
        usage = TokenUsage(
            input_tokens=(len(request.system) + len(request.user)) // 4, output_tokens=20
        )
        if attempt == 1 and self._breaks(request.custom_id):
            return LLMResult(request.custom_id, "succeeded", text="not json", usage=usage)
        text = json.dumps(fake_label(request.user), ensure_ascii=False)
        return LLMResult(request.custom_id, "succeeded", text=text, usage=usage)

    def _breaks(self, custom_id: str) -> bool:
        if self.invalid_first_every <= 0:
            return False
        value = int(hashlib.sha256(custom_id.encode()).hexdigest()[:8], 16)
        return value % self.invalid_first_every == 0
