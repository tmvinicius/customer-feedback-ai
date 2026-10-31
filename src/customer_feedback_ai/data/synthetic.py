"""Synthetic complaints in the ConsumerBR format.

Every company, person and text here is invented. The generator exists so the
pipeline can be tested and demonstrated without the corpus (AGENTS.md, G1).
It reproduces the traps the pipeline must handle: missing dates, exact and
near duplicates, anonymization tags, multi-line text and a long tail of
companies.
"""

import csv
import random
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from customer_feedback_ai.data.schema import RAW_COLUMN_NAMES

COMPANIES: tuple[str, ...] = (
    "Telefonia Aurora",
    "Banco Horizonte",
    "Loja Virtual Pé de Ipê",
    "Energia Vale Verde",
    "Transportes Rápido Sul",
    "Seguradora Âncora",
    "Internet Fibra Clara",
    "Varejo Casa & Cia",
    "Cartões Estrela",
    "Companhia Aérea Céu Azul",
    "Plano de Saúde Bem Viver",
    "Marketplace Feira Livre",
    "Financeira Passo Certo",
    "Água e Saneamento Rio Claro",
    "Eletrônicos Faísca",
    "Academia Movimento",
    "Streaming Tela Cheia",
    "Imobiliária Porta Aberta",
    "Farmácia Saúde Já",
    "Escola Online Saber",
)

_TEMPLATES: dict[str, tuple[str, ...]] = {
    "cobranca_indevida": (
        "Fui cobrado em R$ {valor} na fatura de {mes} por um serviço que nunca contratei. "
        "Já liguei {n} vezes e ninguém resolve.",
        "Meu nome é [NOME] e recebi uma cobrança duplicada de R$ {valor}. Quero o cancelamento "
        "da cobrança indevida.",
    ),
    "cancelamento": (
        "Solicitei o cancelamento do plano no dia {data}, protocolo {protocolo}, e continuo "
        "sendo cobrado.",
        "Tento cancelar a assinatura há {n} semanas e o atendimento sempre transfere a ligação.",
    ),
    "reembolso_estorno": (
        "Devolvi o produto no dia {data} e até agora não recebi o estorno de R$ {valor}.",
        "Cancelei a compra do pedido {pedido} dentro do prazo e o reembolso não foi feito.",
    ),
    "entrega_atraso": (
        "Comprei no dia {data} o pedido {pedido} com entrega prevista em {n} dias e nada chegou.",
        "O rastreio do pedido {pedido} está parado há {n} dias.\nPreciso do produto com urgência.",
    ),
    "produto_defeito": (
        "O aparelho parou de funcionar depois de {n} dias de uso. "
        "A assistência não aceita a troca.",
        "Recebi o produto quebrado, pedido {pedido}. "
        "Enviei fotos para [EMAIL] e não tive resposta.",
    ),
    "servico_indisponivel": (
        "Estou sem internet há {n} dias e trabalho em casa. Protocolo {protocolo}.",
        "A energia foi cortada mesmo com as contas pagas. Tenho um familiar que usa aparelho "
        "de oxigênio em casa.",
    ),
    "fraude_golpe": (
        "Apareceram {n} compras que não reconheço no meu cartão, total de R$ {valor}. "
        "O cartão continua ativo.",
        "Abriram uma conta no meu nome com meus dados. Fiz boletim de ocorrência no dia {data}.",
    ),
    "oferta_contrato": (
        "O anúncio dizia R$ {valor} por mês, mas o contrato veio com outro valor.",
        'A empresa mudou as condições do plano sem aviso. O "desconto vitalício" sumiu.',
    ),
    "atendimento": (
        "Abri {n} chamados e nenhum foi respondido. O atendente [NOME] encerrou a conversa.",
        "O chat fica horas na fila e cai sempre que chega a minha vez.",
    ),
    "dados_cadastro": (
        "Pedi a correção do meu endereço no cadastro e o sistema continua com o dado errado.",
        "Quero a exclusão dos meus dados, pedido feito no dia {data}, e não recebi confirmação.",
    ),
    "credito_negativacao": (
        "Meu nome foi negativado por uma dívida de R$ {valor} que já foi paga.",
        "Pedi a renegociação do empréstimo e a parcela veio maior que a combinada.",
    ),
}

# A closing sentence with variable parts keeps accidental duplicates rare, so the
# exact duplicates in the output are mostly the ones injected on purpose.
_CLOSINGS = (
    " Aguardo uma solução desde {data}, protocolo {protocolo}.",
    " Já são {n} dias sem resposta ao protocolo {protocolo}.",
    " Protocolo do primeiro contato: {protocolo}.",
    " Peço que resolvam até o dia {data}. Protocolo {protocolo}.",
    " Gastei R$ {valor} com isso até agora (protocolo {protocolo}).",
)

_RESPONSES_STANDARD = (
    "Prezado(a) [NOME], agradecemos o contato. Sua solicitação foi encaminhada à área responsável.",
    "Olá, [NOME]. Lamentamos o ocorrido. Entraremos em contato pelos canais cadastrados.",
)
_RESPONSE_CUSTOM = (
    "Olá, [NOME]. Verificamos o caso do protocolo {protocolo} e o ajuste foi feito no dia {data}. "
    "Permanecemos à disposição."
)
_STATUSES = (("Resolvida", 0.28), ("Não Resolvida", 0.23), ("Não Avaliada", 0.49))
_START = datetime(2021, 5, 1)
_END = datetime(2025, 4, 30, 23, 59, 59)


def _fill(template: str, rng: random.Random) -> str:
    return template.format(
        valor=f"{rng.randint(10, 3000)},{rng.randint(0, 99):02d}",
        mes=rng.choice(("janeiro", "março", "julho", "outubro")),
        n=rng.randint(2, 30),
        data=f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2024",
        protocolo=rng.randint(10**8, 10**9 - 1),
        pedido=f"PED-{rng.randint(10**5, 10**6 - 1)}",
    )


def _timestamp(rng: random.Random) -> datetime:
    seconds = int((_END - _START).total_seconds())
    return _START + timedelta(seconds=rng.randint(0, seconds))


def _variant(text: str, rng: random.Random) -> str:
    """Same text after the dedup normalization: different case or spacing."""
    choice = rng.randint(0, 2)
    if choice == 0:
        return text.upper()
    if choice == 1:
        return "  " + text.replace(" ", "  ", 3) + " \n"
    return text


def generate_rows(n: int, seed: int) -> Iterator[dict[str, str]]:
    """Yield `n` synthetic rows as CSV-ready strings. Same `n` and `seed`, same rows."""
    rng = random.Random(seed)
    company_weights = [1 / (rank + 1) for rank in range(len(COMPANIES))]
    topics = sorted(_TEMPLATES)
    previous: list[str] = []
    for index in range(n):
        if previous and rng.random() < 0.05:
            text = _variant(rng.choice(previous), rng)
        else:
            template = rng.choice(_TEMPLATES[rng.choice(topics)]) + rng.choice(_CLOSINGS)
            text = _fill(template, rng)
            previous.append(text)
        if rng.random() < 0.01:
            text = "   "
        opened = None if rng.random() < 0.1 else _timestamp(rng)
        has_response = rng.random() < 0.98
        standardized = has_response and rng.random() < 0.92
        response = ""
        if has_response:
            response = (
                rng.choice(_RESPONSES_STANDARD) if standardized else _fill(_RESPONSE_CUSTOM, rng)
            )
        status = ""
        if opened is not None:
            status = rng.choices([s for s, _ in _STATUSES], [w for _, w in _STATUSES])[0]
        rating = str(rng.randint(1, 5)) if status in ("Resolvida", "Não Resolvida") else ""
        answered = opened + timedelta(days=rng.randint(1, 10)) if opened and has_response else None
        yield {
            "ID": f"SYN-{index:07d}",
            "id_reclamacao": str(100_000 + index),
            "reclamacao_labeled": text,
            "empresa": rng.choices(COMPANIES, company_weights)[0],
            "data_abertura": "" if opened is None else opened.isoformat(sep=" "),
            "localizacao": ""
            if opened is None
            else rng.choice(("SP", "RJ", "MG", "BA", "RS", "PE")),
            "resposta_labeled": response,
            "padronizada": "" if not has_response else str(standardized),
            "status": status,
            "avaliacao_nota": rating,
            "data_resposta": "" if answered is None else answered.isoformat(sep=" "),
            "avaliacao_comentario": "Comentário sintético." if rating else "",
        }


def write_synthetic_csv(path: Path, n: int, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RAW_COLUMN_NAMES))
        writer.writeheader()
        writer.writerows(generate_rows(n, seed))
