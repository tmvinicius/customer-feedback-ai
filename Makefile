.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
# --locked fails if uv.lock is out of date with pyproject.toml.
RUN := $(UV) run --locked

# Planned targets fail on purpose until their milestone is implemented, so a
# missing step never looks like a success (AGENTS.md, rule 14).
NOT_IMPLEMENTED = echo "make $@: ainda não implementado (marco $(1)). Veja AGENTS.md, seção 17." >&2; exit 1

# Data targets read DATA_DIR from the environment or .env (default: data).
# Command-line values are passed on, e.g. `make data DATA_DIR=data/synthetic`.
# Input for `make splits`: silver (full corpus) or dev_sample.
SOURCE ?= silver
SYNTHETIC_ROWS ?= 20000
# label-silver: LLM=fake runs offline; APPROVED_USD records the G4 approval;
# WAIT=1 polls until the batch ends. CONFIRM_COST=1 is read from the environment.
LLM ?= anthropic

.PHONY: help setup lint format typecheck test \
	synthetic-data data sample splits taxonomy-sample \
	annotate gold-report label-silver train-local eval-dev \
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

typecheck: ## mypy em modo estrito (src, tests e ui)
	$(RUN) mypy src tests ui

test: ## Testes unitários
	$(RUN) pytest

# --- Dados (M1) ---

synthetic-data: ## Corpus inventado em DATA_DIR/raw; use DATA_DIR=data/synthetic
	$(RUN) python -m customer_feedback_ai.pipelines.synthetic --rows $(SYNTHETIC_ROWS)

data: ## raw -> bronze -> silver, com perfil e manifestos (RAW=arquivo.csv opcional)
	$(RUN) python -m customer_feedback_ai.pipelines.data $(if $(RAW),--raw $(RAW))

sample: ## Gera dev_sample com cerca de 50 mil linhas a partir da silver
	$(RUN) python -m customer_feedback_ai.pipelines.sample

splits: ## Gera splits temporais e manifestos (SOURCE=silver ou dev_sample)
	$(RUN) python -m customer_feedback_ai.pipelines.splits --source $(SOURCE)

taxonomy-sample: ## Exporta 200 reclamações de train para a leitura antes de G2
	$(RUN) python -m customer_feedback_ai.pipelines.taxonomy_sample --source $(SOURCE)

# --- Rótulos (M2) ---

annotate: ## Prepara a fila do gold set e abre a ferramenta de anotação
	$(RUN) python -m customer_feedback_ai.pipelines.gold_sample
	$(RUN) streamlit run ui/annotate.py --server.headless true \
		--browser.gatherUsageStats false --client.toolbarMode minimal

gold-report: ## Exporta gold_dev e gold_test e gera o relatório de cobertura e kappa
	$(RUN) python -m customer_feedback_ai.pipelines.gold_report

label-silver: ## Rótulos silver em lote; exige CONFIRM_COST=1 e G1 (LLM=fake roda offline)
	$(RUN) python -m customer_feedback_ai.pipelines.label_silver --llm $(LLM) \
		$(if $(APPROVED_USD),--approved-usd $(APPROVED_USD)) $(if $(WAIT),--wait)

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
