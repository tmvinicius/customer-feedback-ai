# Status

Marco ativo: M2, Rótulos. O código está pronto e testado com dados sintéticos e o `FakeLLM`. O aceite depende de G1 (corpus real e envio ao LLM), de G3 (anotação humana) e do primeiro lote silver real.
Último commit na `main`: `b249211` (docs: add status, decision log and test). As mudanças do M1, da G2 parcial e do M2 aguardam revisão e commit do mantenedor.

## Concluído

### M0

- Fundação integrada na `main`, com a licença Apache 2.0 do código decidida. O aceite formal depende de G1.

### M1

- Ingestão, limpeza, deduplicação, splits, manifestos, EDA, `dev_sample` e amostra para a taxonomia, testados com dados sintéticos. Detalhes em `docs/data_card.md` e nas decisões de 2026-11-04.
- G2 parcial (2026-11-10): as regras de urgência foram aprovadas. A lista de temas depende da leitura das 200 reclamações.
- Pendente no aceite do M1: rodar no corpus real e documentar as divergências em relação ao artigo (G1), e concluir G2.

### M2

- **Gold set:** `make annotate` sorteia a fila uma única vez (150 itens de `gold_dev` em `val`; 350 de `gold_test` em `test`, com 25% de empresas ocultas; 10% de cada conjunto marcados para reanotação) e abre a ferramenta de anotação cega em Streamlit.
- **Rótulos:** ficam em JSONL só de acréscimo, e vale o último registro. A reanotação abre só depois de 7 dias e não mostra o primeiro rótulo.
- **Relatório:** `make gold-report` exporta `gold_dev` e `gold_test`, mede o kappa da reanotação e a concordância do LLM com `gold_dev`, e emite os alertas da seção 7 (tema com menos de 5 exemplos, menos de 30 casos de urgência alta).
- **Rótulos silver:** `make label-silver` cobre `silver_train` (20 mil de `train`), `silver_val` (2 mil de `val`, sem os itens de `gold_dev`) e `gold_dev_llm`. Usa o Message Batches API com structured outputs, reenvia uma vez as respostas inválidas e não paga duas vezes pela mesma requisição, graças ao cache. O manifesto registra o custo estimado e o real.
- **Travas:** sem `ALLOW_EXTERNAL_LLM=true` (G1), o envio é bloqueado; sem `CONFIRM_COST=1`, só a estimativa aparece; acima de US$ 5, é preciso `APPROVED_USD` (G4); o teto de US$ 30 vale para o total gasto.
- **Camada de LLM:** `BatchLLMClient`, cliente da Anthropic, `FakeLLM`, preços em `configs/pricing.yaml` (conferidos em 2026-11-11), cache e registro de custo sem texto. A camada foi antecipada do M3.
- **Prompt:** `prompts/classify/v1.md`, com o texto entre tags e a instrução de tratá-lo como dado.
- **Evidências:**
  - `make lint typecheck test`: Ruff sem erros, 74 arquivos formatados, mypy strict sem erros em 66 arquivos (agora inclui `ui/`), 187 testes aprovados.
  - Os testes falharam como esperado com dois defeitos introduzidos de propósito: remover a trava de G1 e voltar a compartilhar o cache entre o `FakeLLM` e o cliente real.
  - Esse segundo defeito existia de fato na primeira versão e foi encontrado na rodada sintética: rótulos falsos teriam sido reaproveitados por uma execução real. O defeito foi corrigido, e o teste fica como proteção.
  - Rodada sintética (20 mil linhas): fila com 150 e 350 itens; `make label-silver LLM=fake` rotulou 11.382 itens a custo zero. O cliente real foi bloqueado sem G1 e, com G1 mas sem `CONFIRM_COST=1`, mostrou a estimativa.
  - `make annotate` subiu a ferramenta (`/_stcore/health` respondeu `ok`). A tela foi conferida com um print sobre dados sintéticos, e o teste com `AppTest` grava um rótulo de ponta a ponta.
  - Estimativa para o corpus real, calculada com `estimate_cost`: US$ 2,73 para 22.150 requisições (32,5 milhões de tokens de entrada e 4,4 milhões de saída), abaixo do limite de US$ 5. A conta usa o prompt v1, textos com a média do artigo (772 caracteres), 200 tokens de saída por item e o preço do Batch do Haiku 5.5. É só um indicativo: o valor que conta é o que `make label-silver` mostrar com os textos reais.

## Próximo passo

- Mantenedor: responder G1. Sem ela, nada roda no corpus real.
- Depois de G1: rodar o pipeline do M1 no corpus, ler as 200 reclamações e concluir G2 (lista de temas).
- Mantenedor (G3): anotar `gold_dev` com `make annotate`, reanotar os 10% depois de 7 dias e rodar `make gold-report`.
- Com G1 e a chave da API no `.env`: rodar `make label-silver`, revisar a estimativa e submeter com `CONFIRM_COST=1`. Depois comparar o custo real com o estimado no manifesto.
- Anotar `gold_test` só depois de revisar a taxonomia com base em `gold_dev`, se algum tema tiver menos de 5 exemplos.

## Bloqueios

- G1 pendente (mantenedor). Bloqueia o corpus real, o envio de texto ao LLM e, portanto, os rótulos silver reais.
- G2 parcial (mantenedor). Falta a lista de temas.
- G3 (mantenedor). A anotação do gold set é humana.
- `zenodo.org` e a API da Anthropic não foram usados nesta sessão de nuvem. Nenhum rótulo real, custo real ou concordância real foi medido.
- O formato real do CSV ainda não foi visto (ver M1).
