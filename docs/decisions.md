# Registro de decisões

Este arquivo registra mudanças em stack, split, métrica, threshold, escopo ou fonte de dados, e o resultado das decisões humanas G1 a G6 (AGENTS.md, seções 4 e 18). Consulte-o antes de mudar qualquer decisão do plano.

Formato de cada entrada:

```markdown
## AAAA-MM-DD: título

Decisão:
Motivo:
Alternativas:
Consequências:
```

## Decisões humanas

| ID  | Quando                                | Status   | Data | Registro |
| --- | ------------------------------------- | -------- | ---- | -------- |
| G1  | Antes de baixar ou processar o corpus | pendente | -    | -        |
| G2  | Fim do M1                             | parcial: regras de urgência aprovadas, temas pendentes | 2026-11-10 | 2026-11-10: Regras de urgência das diretrizes |
| G3  | Durante o M2                          | pendente | -    | -        |
| G4  | Antes de job LLM acima do limite      | pendente | -    | -        |
| G5  | Antes de avaliar em `test`            | pendente | -    | -        |
| G6  | M6                                    | parcial: licença do código decidida, publicação pendente | 2026-11-04 | 2026-11-04: Licença do código |

Quando uma decisão humana for tomada, atualize a tabela e crie uma entrada abaixo com a resposta do mantenedor.

## 2026-11-01: Ferramentas e convenções da fundação (M0)

Decisão:

- Pacote em layout `src/`, construído com o backend `uv_build`, e Python fixado em 3.12 (`requires-python = ">=3.12,<3.13"` e `.python-version`).
- Dependências entram no `pyproject.toml` no marco em que passam a ser usadas. O M0 declara apenas `pydantic` e `pydantic-settings`, mais `ruff`, `mypy` e `pytest` no grupo `dev`.
- Configuração em `settings.py` com `pydantic-settings`, lendo variáveis de ambiente e `.env`. Todo campo de `Settings` precisa estar em `.env.example`, e um teste garante isso.
- mypy em modo `strict`, com o plugin do Pydantic, sobre `src` e `tests`.
- `make lint` também verifica a formatação (`ruff format --check`), e todos os alvos usam `uv run --locked`.
- Alvos do Makefile de marcos futuros já existem, mas falham com mensagem explícita até serem implementados.
- Testes de higiene do repositório verificam com `git check-ignore` e `git ls-files` que dados, pesos e segredos não entram no Git.

Motivo: reprodução simples com `uv.lock`, CI rápida e proteção automática das regras 6 e 14 do AGENTS.md. Declarar PyTorch e Transformers desde o M0 deixaria cada execução da CI muito mais lenta sem nenhum uso.

Alternativas: declarar toda a stack no M0; `hatchling` como backend; `os.environ` com `python-dotenv` no lugar de `pydantic-settings`; mypy sem `strict`.

Consequências: o `uv.lock` muda a cada marco que adiciona dependências. `pydantic-settings` é uma dependência pequena que não estava na tabela de stack. Código novo precisa de anotações de tipo completas, inclusive nos testes.

## 2026-11-01: Licença do código

Decisão: o código do repositório usa a Apache License 2.0, conforme o arquivo `LICENSE` já versionado. O `pyproject.toml` declara `license = "Apache-2.0"` e `license-files = ["LICENSE"]`. A licença cobre apenas o código. O corpus ConsumerBR, os dados derivados e os pesos treinados com ele seguem a licença do Zenodo, que G1 avalia. A aprovação da publicação do repositório continua pendente em G6.
Motivo: decisão do mantenedor. A Apache 2.0 é permissiva, inclui concessão explícita de patentes e já estava no repositório desde o commit inicial.
Alternativas: MIT; adiar a escolha até G6 e remover o `LICENSE` até lá.
Consequências: o README deixa de dizer que a licença será definida depois. O classificador `Private :: Do Not Upload` continua até G6. A publicação de modelos derivados do corpus não é autorizada por esta decisão; depende de G1.

## 2026-11-01: Pipeline de dados do M1

Decisão:

- DuckDB lê o CSV com todas as colunas como texto e converte cada uma com regras explícitas. Valores inválidos viram nulos e são contados. Acima de 1% por coluna (`configs/data.yaml`), o pipeline para.
- Configuração da ingestão, das amostras e dos valores de referência do artigo em um arquivo novo, `configs/data.yaml`.
- Novas dependências: `duckdb` (já prevista na stack) e `pyyaml`, para ler os YAMLs.
- Dois alvos novos no Makefile: `make synthetic-data`, que gera um corpus inventado para testar o pipeline sem o ConsumerBR, e `make taxonomy-sample`, que exporta as 200 reclamações para a leitura antes de G2. `make splits` e `make taxonomy-sample` aceitam `SOURCE=dev_sample`.
- O `dev_sample` é retirado da camada silver, com todas as janelas de data. Ele serve para iterar no pipeline, não para escolher modelos. A regra 4 continua valendo para o `test` dele.
- O perfil (EDA) é gravado em JSON em `data/eda/`, fora do Git, e compara o bronze com os valores do artigo sem parar o pipeline.

Motivo: tipagem explícita evita que um formato de data ou booleano inesperado vire dado errado em silêncio. O corpus sintético permite desenvolver e testar o M1 enquanto G1 está pendente.

Alternativas: deixar o DuckDB inferir os tipos; pandas no lugar do DuckDB; colocar os parâmetros de ingestão em `settings.py`.

Consequências: se o formato real do CSV for diferente do esperado, o pipeline para com uma mensagem que aponta a coluna, e o ajuste é feito em `configs/data.yaml`.

## 2026-11-01: Deduplicação e quase duplicatas

Decisão:

- Duplicatas exatas são definidas pelo SHA-256 do texto normalizado (NFC, minúsculas, espaços colapsados) e removidas no corpus inteiro, antes dos splits. Fica a ocorrência mais antiga. Linhas com data vencem as sem data.
- Quase duplicatas são marcadas com `loose_hash` (texto sem acentos, dígitos, pontuação e tags) no corpus inteiro, e não são removidas. O manifesto dos splits informa quantos grupos de `val`, `test` e `test_unseen_company` também aparecem em `train`.

Motivo: deduplicar antes do split garante que o mesmo texto nunca esteja em dois splits. O `loose_hash` mede quase duplicatas em todo o corpus pelo mesmo custo de uma amostra.

Alternativas: MinHash com LSH por amostragem, como o plano sugeria; remover também as quase duplicatas.

Consequências: paráfrases não são detectadas. Remover quase duplicatas fica para depois, se a medição mostrar que elas inflam as métricas.

## 2026-11-01: Empresas ocultas e janelas dos splits

Decisão:

- Uma empresa é oculta quando o SHA-256 de `<salt>:<nome normalizado>` cai abaixo de 5%. A decisão de cada empresa não depende das outras.
- Reclamações de empresas ocultas na janela de `test` formam `test_unseen_company`. As anteriores a 2024-07-01 ficam fora de todos os splits.
- O nome é normalizado com minúsculas, sem acentos e com espaços colapsados.
- As janelas comparam a data, sem hora, de `data_abertura`, com limites inclusivos.

Motivo: a regra por empresa dá o mesmo resultado no corpus completo e no `dev_sample`. Manter só a janela de `test` em `test_unseen_company` evita misturar generalização para empresas novas com generalização no tempo.

Alternativas: ordenar as empresas pelo hash e pegar exatamente 5%; incluir todas as reclamações das empresas ocultas em `test_unseen_company`.

Consequências: a fração de empresas ocultas é aproximada. Uma empresa muito grande sorteada como oculta reduz bastante o volume de `train`. O manifesto registra quantas empresas e linhas ficaram ocultas.

## 2026-11-01: Regras de urgência das diretrizes

Decisão: o mantenedor aprovou três regras de `docs/annotation_guidelines.md`:

- Telefonia e internet contam como serviço essencial. A interrupção no momento do relato leva a urgência `alta`. Instabilidade ou lentidão sem interrupção não conta.
- Na dúvida, o anotador escolhe o rótulo que julga mais provável e marca a dúvida. Não escolhe o nível mais alto por precaução.
- Negativação já feita é `media`. Ela só passa a `alta` com outro critério de `alta`, como prazo crítico ou vulnerabilidade relatada.

A lista de temas continua pendente até a leitura das 200 reclamações, que depende de G1. G2 fica parcial até lá.

Motivo: telecomunicações estão na lista de serviços essenciais da Lei 7.783/89, e uma regra simples evita dúvida na anotação. O gold set precisa refletir o texto. A meta de recall de urgência alta (>= 0,90) é garantida pelas regras de segurança da cascata, não por rótulos inflados. Negativação é um prejuízo em andamento, sem risco imediato por si só.

Alternativas: só água, energia, gás e saúde como essenciais; na dúvida, escolher o nível mais alto; negativação sempre `alta`.

Consequências: o gold set pode ter menos casos de `alta`. Se `gold_test` ficar com menos de 30, vale a regra do conjunto extra enriquecido (AGENTS.md, seção 7).
