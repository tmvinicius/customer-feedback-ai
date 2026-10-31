.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
# --locked fails if uv.lock is out of date with pyproject.toml.
RUN := $(UV) run --locked

# Planned targets fail on purpose until their milestone is implemented, so a
# missing step never looks like a success (AGENTS.md, rule 14).
NOT_IMPLEMENTED = echo "make $@: ainda não implementado (marco $(1)). Veja AGENTS.md, seção 17." >&2; exit 1

.PHONY: help setup lint format typecheck test \
	data sample splits annotate label-silver train-local eval-dev \
	build-index eval-retrieval eval-offline eval-final report demo

help: ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'

# --- Qualidade (M0) ---

setup: ## Instala dependências a partir do uv.lock
	$(UV) sync --locked

lint: ## Ruff: lint e checagem de formatação
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Ruff: formata o código e aplica correções seguras
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## mypy em modo estrito
	$(RUN) mypy

test: ## Testes unitários
	$(RUN) pytest

# --- Dados (M1) ---

data: ## raw -> bronze -> silver (M1)
	@$(call NOT_IMPLEMENTED,M1)

sample: ## Gera dev_sample com cerca de 50 mil linhas (M1)
	@$(call NOT_IMPLEMENTED,M1)

splits: ## Gera splits temporais e manifestos (M1)
	@$(call NOT_IMPLEMENTED,M1)

# --- Rótulos (M2) ---

annotate: ## Abre a ferramenta de anotação (M2)
	@$(call NOT_IMPLEMENTED,M2)

label-silver: ## Lote LLM de rótulos silver, exige CONFIRM_COST=1 (M2)
	@$(call NOT_IMPLEMENTED,M2)

# --- Modelos e avaliação (M3 a M6) ---

train-local: ## Treina B0, B1, C1, C2 e C3 (M3)
	@$(call NOT_IMPLEMENTED,M3)

eval-dev: ## L2: avalia modelos e cascata em gold_dev, usa LLM real (M3)
	@$(call NOT_IMPLEMENTED,M3)

eval-offline: ## L0 e L1: FakeLLM e replay de cassettes (M3)
	@$(call NOT_IMPLEMENTED,M3)

build-index: ## Constrói o índice de casos (M5)
	@$(call NOT_IMPLEMENTED,M5)

eval-retrieval: ## Compara BM25, vetorial e híbrido (M5)
	@$(call NOT_IMPLEMENTED,M5)

eval-final: ## L3: gold_test, test_unseen_company e redteam, exige G5 (M6)
	@$(call NOT_IMPLEMENTED,M6)

report: ## Atualiza os resultados do README a partir de reports/metrics.json (M3)
	@$(call NOT_IMPLEMENTED,M3)

demo: ## Abre a interface local em Streamlit (M3)
	@$(call NOT_IMPLEMENTED,M3)
