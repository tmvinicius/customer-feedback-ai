# Status

Marco ativo: M1, Dados e taxonomia. O código está pronto e testado com dados sintéticos. O aceite depende de G1 (rodar no corpus real) e de G2 (aprovar taxonomia e diretrizes).
Último commit: `b249211` (docs: add status, decision log and test). As mudanças do M1 ainda não foram commitadas e aguardam revisão do mantenedor.

## Concluído

### M0

- Fundação aceita pelo mantenedor e integrada na `main` (commits `44de5a3` a `b249211`), com a licença Apache 2.0 do código decidida.
- O aceite formal do M0 ainda depende de G1.

### M1

- Ingestão raw -> bronze com DuckDB, leitura do CSV como texto e conversão explícita de tipos. Falhas de conversão são contadas, e o pipeline para acima de 1% por coluna.
- Limpeza bronze -> silver: NFC, espaços nas pontas, tags `[NOME]` preservadas, remoção de reclamações vazias e deduplicação pelo hash do texto normalizado, mantendo a ocorrência mais antiga.
- Splits `train`, `val`, `test` e `test_unseen_company` por data e por hash da empresa, com verificação automática de sobreposição, janelas e empresas ocultas.
- Manifestos em todas as etapas, com SHA-256 e tamanho das entradas e saídas, contagens, seed, configuração com hash, commit e versões.
- EDA enxuta em `data/eda/*.json`: faltantes, duplicatas, tamanhos, distribuição por empresa, status e nota, e comparação com o artigo.
- `make sample` (`dev_sample`), `make taxonomy-sample` (200 reclamações de `train`) e `make synthetic-data` (corpus inventado).
- `configs/data.yaml`, `configs/splits.yaml` e `configs/taxonomy.yaml`.
- `docs/data_card.md` e `docs/annotation_guidelines.md` em rascunho, para G2.
- G2 parcial (2026-11-10): o mantenedor aprovou as regras de urgência para telefonia e internet, para dúvida entre níveis e para negativação. Elas estão aplicadas nas diretrizes e registradas em `docs/decisions.md`.
- Evidências:
  - `make lint typecheck test`: Ruff sem erros, 50 arquivos formatados, mypy strict sem erros em 43 arquivos, 119 testes aprovados.
  - Reprodutibilidade: o pipeline completo roda duas vezes sobre o mesmo CSV sintético, e manifestos (sem data e commit), Parquets e perfis são idênticos (`tests/unit/test_pipeline_reproducibility.py`).
  - Splits sem sobreposição de `ID` e `text_hash`, empresas ocultas só em `test_unseen_company`, datas dentro das janelas e limites inclusivos (`tests/unit/test_splits.py`).
  - Os testes falharam como esperado com dois defeitos introduzidos de propósito: manter a duplicata mais nova e deixar empresas ocultas entrarem em `train`. No segundo, o próprio pipeline recusou gravar os splits.
  - `make synthetic-data data sample splits taxonomy-sample DATA_DIR=<pasta>` rodou do começo ao fim com 20 mil linhas.
  - Escala: 1 milhão de linhas sintéticas (333 MB) levaram 17 s e cerca de 2 GB de memória em `make data`, e 3,3 s em `make splits`, numa máquina com 4 CPUs. O corpus real tem cerca de 15 vezes esse tamanho e textos mais longos, então isso é só um indicativo.

## Próximo passo

- Mantenedor: ler a licença do ConsumerBR no Zenodo e responder G1.
- Depois de G1, na máquina do mantenedor: colocar o CSV em `data/raw/` e rodar `make data sample splits taxonomy-sample`.
- Preencher os valores observados em `docs/data_card.md` a partir de `data/eda/bronze_profile.json` e dos manifestos, e explicar as divergências em relação ao artigo.
- Mantenedor: ler `data/gold/taxonomy_review_sample.csv`, dizer se a lista de temas cobre bem as reclamações (unir, dividir ou criar temas) e concluir G2.

## Bloqueios

- G1 pendente (mantenedor). Sem ele, o pipeline não roda no corpus real e as divergências em relação ao artigo não podem ser medidas.
- G2 parcial (mantenedor). Falta aprovar a lista de temas, o que depende da leitura das 200 reclamações, que depende de G1.
- `zenodo.org` está bloqueado na rede da sessão de nuvem do agente. O corpus precisa ser processado na máquina do mantenedor.
- O formato real do CSV (delimitador, formato de datas e de booleanos, valores de `status`) não foi visto. Se divergir, `make data` para e aponta a coluna, e o ajuste é feito em `configs/data.yaml`.
