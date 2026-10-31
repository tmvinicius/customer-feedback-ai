# Status

Marco ativo: M0, Fundação. A implementação está concluída, mas o aceite depende de G1.
Último commit: `570e36e` (initial commit). As mudanças do M0 ainda não foram commitadas e aguardam revisão do mantenedor.

## Concluído

- Projeto Python 3.12 em layout `src/` com `pyproject.toml`, `uv.lock` e `.python-version`.
  - `uv lock` resolveu 20 pacotes. `make setup` (`uv sync --locked`) instalou o ambiente com CPython 3.12.16 (fixado em 3.12 por `.python-version`).
- `Makefile` com todos os alvos da seção 15. `setup`, `lint`, `format`, `typecheck` e `test` funcionam. Os alvos dos marcos seguintes avisam o marco e terminam com erro.
  - `make data` imprimiu `ainda não implementado (marco M1)` e terminou com código 2.
  - `make help` lista os 19 alvos.
- `src/customer_feedback_ai/settings.py` com modelos, teto de custo, limite de aprovação, `CASES_INDEX` e `DATA_DIR`. `.env.example` documenta todos os campos.
- Testes básicos em `tests/unit/`: configuração (padrões do plano, sobrescrita por ambiente, validação, chave mascarada, sincronia com `.env.example`) e higiene do repositório (dados, pesos e segredos ignorados e fora do Git).
  - `make lint typecheck test`: Ruff sem erros e 11 arquivos formatados (6 `.py` e 5 `.md`, porque o Ruff 0.17 também verifica blocos de Python em Markdown). mypy strict sem erros em 6 arquivos. pytest com 24 testes aprovados.
  - Os testes de higiene falharam como esperado quando as regras `data/` e `.env` foram removidas do `.gitignore`, e quando um CSV em `data/raw/` foi adicionado a um índice temporário do Git.
- CI em `.github/workflows/ci.yml`: `make setup` e depois `make lint typecheck test`, em push na `main`, pull requests e execução manual. O workflow ainda não rodou no GitHub.
- `docs/decisions.md`, com a tabela de decisões humanas e a decisão sobre as ferramentas do M0, e `docs/test_set_log.md`, vazio.
- README: pré-requisitos e alvos disponíveis em "Como executar".
- Licença do código: Apache 2.0, por decisão do mantenedor (`docs/decisions.md`, 2026-11-04). README, AGENTS.md e `pyproject.toml` atualizados. A parte de G6 sobre publicação do repositório continua pendente.

## Próximo passo

- Mantenedor: ler a licença do ConsumerBR no Zenodo e responder G1.
- Mantenedor: commitar as mudanças e confirmar que a CI passa no GitHub.
- Depois de G1: registrar a resposta em `docs/decisions.md`, fechar o M0 e iniciar o M1.

## Bloqueios

- G1 pendente (mantenedor). É preciso confirmar na licença do Zenodo: uso em portfólio público, envio de texto a API externa (LLM e agente de código), publicação de modelos derivados e exibição de casos na demo.
- `zenodo.org` está bloqueado na rede da sessão de nuvem do agente. O agente não conseguiu ler a página da licença e não consegue baixar o corpus nesse ambiente (mantenedor).
