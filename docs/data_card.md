# Data card: ConsumerBR no customer-feedback-ai

Status: pipeline implementado e testado só com dados sintéticos. Os valores observados no corpus real estão `pendente` até G1 ser aprovado e `make data` rodar no ConsumerBR.

## Fonte

- **Corpus:** ConsumerBR, reclamações e respostas em português brasileiro publicadas no Consumidor.gov.br e anonimizadas pela UFMG.
- **Artigo:** Duarte et al., PROPOR 2026, pp. 667-675.
- **Dataset:** Zenodo, DOI [`10.5281/zenodo.18022568`](https://doi.org/10.5281/zenodo.18022568).
- **Arquivo esperado:** um CSV de cerca de 5,2 GiB em `data/raw/`. Nome e hash do arquivo ficam em `data/manifests/bronze.json` depois da primeira execução.
- **Não usar:** os dados abertos oficiais do Consumidor.gov.br. Eles não trazem o texto e não devem ser cruzados com o corpus, pelo risco de reidentificação.

## Licença e uso

| Uso                                      | Situação                    |
| ---------------------------------------- | --------------------------- |
| Uso em portfólio público                 | pendente (G1)               |
| Envio de texto a API externa             | pendente (G1)               |
| Publicação de modelos derivados          | pendente (G1)               |
| Exibição de casos reais na demo          | pendente (G1)               |
| Redistribuição dos dados neste repositório | não permitida (regras 6 e 9) |

Segundo o artigo, o uso é restrito a pesquisa. O texto exato da licença precisa ser lido no Zenodo pelo mantenedor e registrado em `docs/decisions.md`.

## Campos e uso permitido

A regra está em `src/customer_feedback_ai/data/schema.py` e é verificada por `tests/unit/test_schema.py`.

| Campo                  | Tipo      | Uso permitido                                                       |
| ---------------------- | --------- | ------------------------------------------------------------------- |
| `ID`                   | texto     | Identificador                                                       |
| `id_reclamacao`        | inteiro   | Identificador                                                       |
| `reclamacao_labeled`   | texto     | **Única entrada dos classificadores**                               |
| `empresa`              | texto     | Empresas ocultas, filtro de recuperação e análise. Nunca entrada    |
| `data_abertura`        | timestamp | Split temporal e análise                                            |
| `localizacao`          | texto     | Análise opcional                                                    |
| `resposta_labeled`     | texto     | Apenas conteúdo da recuperação                                      |
| `padronizada`          | booleano  | Apenas filtro da recuperação                                        |
| `status`               | texto     | Apenas filtro da recuperação                                        |
| `avaliacao_nota`       | inteiro   | Apenas filtro da recuperação                                        |
| `data_resposta`        | timestamp | Não usar                                                            |
| `avaliacao_comentario` | texto     | Não usar                                                            |

Colunas criadas pelo pipeline:

| Coluna         | Camada        | Conteúdo                                                                 |
| -------------- | ------------- | ------------------------------------------------------------------------ |
| `text_hash`    | silver e gold | SHA-256 do texto normalizado, usado na deduplicação                       |
| `loose_hash`   | silver e gold | SHA-256 do texto sem acentos, dígitos, pontuação e tags, para quase duplicatas |
| `company_key`  | silver e gold | Nome da empresa normalizado, usado nas empresas ocultas                   |
| `split`        | gold          | `train`, `val`, `test` ou `test_unseen_company`                           |

## Processamento

| Etapa                    | Comando          | Saída                                                       |
| ------------------------ | ---------------- | ----------------------------------------------------------- |
| raw -> bronze            | `make data`      | `data/bronze/complaints.parquet`, `data/manifests/bronze.json` |
| bronze -> silver         | `make data`      | `data/silver/complaints.parquet`, `data/manifests/silver.json` |
| Perfil (EDA)             | `make data`      | `data/eda/bronze_profile.json`, `data/eda/silver_profile.json` |
| Amostra de desenvolvimento | `make sample`  | `data/silver/dev_sample.parquet`, `data/manifests/dev_sample.json` |
| Splits                   | `make splits`    | `data/gold/splits/*.parquet`, `data/manifests/splits.json`  |
| Amostra para a taxonomia | `make taxonomy-sample` | `data/gold/taxonomy_review_sample.csv`                |

Todo manifesto registra SHA-256 e tamanho de entradas e saídas, contagens, seed, configuração com hash, commit, versão do pacote e do DuckDB.

### Bronze

- O CSV é lido com todas as colunas como texto, e cada coluna é convertida com regras explícitas.
- Datas aceitam ISO 8601 e os formatos de `configs/data.yaml` (`dd/mm/aaaa`, com ou sem hora). Fuso horário informado no texto é ignorado: vale a data local.
- Booleanos aceitam `true/false`, `1/0`, `sim/não`, `s/n`, `t/f`, `yes/no`, sem diferenciar maiúsculas.
- Inteiros aceitam só números inteiros, ou decimais terminados em `.0`. O DuckDB arredondaria `5.5` para 6, e isso esconderia um erro.
- Valores que não convertem viram nulos e são contados. Acima de 1% por coluna, o pipeline para.
- A ordem das linhas do CSV é mantida.

### Silver

- Textos longos recebem normalização Unicode NFC e perdem espaços nas pontas. Quebras de linha internas e tags como `[NOME]` e `[EMAIL]` são mantidas.
- Empresa, localização e status têm espaços colapsados.
- Reclamações vazias são removidas.
- Duplicatas exatas são definidas pelo hash do texto normalizado (NFC, minúsculas, espaços colapsados). Fica a ocorrência mais antiga. Linhas com data vencem as sem data, para que uma duplicata nunca tire um texto dos splits.
- Quase duplicatas são marcadas por `loose_hash`, mas não removidas.

### Splits

Definidos em `configs/splits.yaml`:

| Split                 | Janela de `data_abertura`      | Empresas  |
| --------------------- | ------------------------------ | --------- |
| `train`               | até 2023-12-31                 | visíveis  |
| `val`                 | 2024-01-01 a 2024-06-30        | visíveis  |
| `test`                | 2024-07-01 até o fim do corpus | visíveis  |
| `test_unseen_company` | 2024-07-01 até o fim do corpus | ocultas   |

- Uma empresa é oculta quando o SHA-256 de `<salt>:<nome normalizado>` cai abaixo de 5%. A fração final de empresas fica perto de 5%, mas não é exata.
- Reclamações de empresas ocultas anteriores a 2024-07-01 ficam fora de todos os splits.
- Reclamações sem `data_abertura` ficam fora e são contadas.
- O pipeline verifica e grava no manifesto: nenhum `ID` ou `text_hash` em dois splits, nenhuma empresa oculta fora de `test_unseen_company` e todas as datas dentro da janela de cada split.

## Valores observados contra o artigo

O perfil compara o bronze com os valores do artigo (`configs/data.yaml`, tolerância de 2%). Divergências não param o pipeline. Elas devem ser explicadas aqui.

| Métrica                              | Artigo     | Observado |
| ------------------------------------ | ---------- | --------- |
| Registros                            | 3.150.552  | pendente  |
| Empresas                             | 1.445      | pendente  |
| Período                              | 05/2021 a 04/2025 | pendente |
| Respostas presentes                  | 98,11%     | pendente  |
| Respostas padronizadas               | 92,29%     | pendente  |
| Caracteres da reclamação, média      | 772        | pendente  |
| Caracteres da reclamação, mediana    | 567        | pendente  |
| Reclamações por empresa, mediana     | 131        | pendente  |
| Reclamações por empresa, máximo      | 131.381    | pendente  |
| Faltantes em `data_abertura`         | 309.653    | pendente  |
| Faltantes em `localizacao`           | 309.653    | pendente  |
| Faltantes em `status`                | 309.658    | pendente  |
| Status: resolvidas / não resolvidas / não avaliadas | 28,06% / 23,45% / 48,49% | pendente |

O artigo não diz se a taxa de respostas padronizadas é calculada sobre todas as reclamações ou só sobre as respondidas. O perfil registra as duas, e a comparação usa a taxa sobre as respondidas.

## Duplicatas e quase duplicatas

| Medida                                       | Valor    |
| -------------------------------------------- | -------- |
| Duplicatas exatas removidas                  | pendente |
| Reclamações vazias removidas                 | pendente |
| Linhas em grupos de quase duplicatas         | pendente |
| Grupos de quase duplicatas compartilhados entre `train` e `val`, `test` e `test_unseen_company` | pendente |

O plano pedia uma estimativa por amostragem. O `loose_hash` mede o corpus inteiro sem custo extra, mas só captura textos que diferem em números, pontuação, acentos ou tags. Paráfrases não são detectadas.

## Privacidade

- O corpus já vem anonimizado, com tags como `[NOME]` e `[EMAIL]`. O pipeline mantém as tags e nunca tenta restaurá-las.
- Nenhum dado do corpus, índice ou peso treinado entra no Git (`.gitignore` e `tests/unit/test_repository_hygiene.py`).
- Logs e mensagens de erro do pipeline trazem contagens e nomes de colunas, nunca o texto das reclamações.
- O perfil traz apenas agregados. A lista das 10 empresas com mais reclamações é o único campo com nomes, e são nomes de empresas.

## Limitações conhecidas

- Uma única plataforma, que pode não representar outros canais.
- O split temporal tende a piorar as métricas, de propósito.
- A fração de empresas ocultas é aproximada, e uma empresa muito grande sorteada como oculta muda bastante o número de linhas de `test_unseen_company`.
- Quase duplicatas por paráfrase não são medidas.

## Como reproduzir

```bash
make data
make sample
make splits
make taxonomy-sample
```

Sem o corpus, o mesmo fluxo roda com dados sintéticos:

```bash
make synthetic-data data sample splits taxonomy-sample DATA_DIR=data/synthetic
```
