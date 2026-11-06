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
| G1  | Antes de baixar ou processar o corpus | aprovado com restrições: pesquisa local permitida; API externa, modelos derivados e casos reais não permitidos; publicação pública limitada a código, métricas agregadas e fixtures sintéticas (G6) | 2026-11-04 | 2026-11-04: G1, licença do ConsumerBR |
| G2  | Fim do M1                             | parcial: regras de urgência aprovadas, temas pendentes | 2026-11-04 | 2026-11-04: Regras de urgência das diretrizes |
| G3  | Durante o M2                          | pendente | -    | -        |
| G4  | Antes de job LLM acima do limite      | sem uso enquanto a API externa não for liberada para texto do corpus | 2026-11-04 | 2026-11-04: Plano B da G1 |
| G5  | Antes de avaliar em `test`            | pendente | -    | -        |
| G6  | M6                                    | parcial: licença do código decidida, publicação pendente | 2026-11-04 | 2026-11-04: Licença do código |

Quando uma decisão humana for tomada, atualize a tabela e crie uma entrada abaixo com a resposta do mantenedor.

## 2026-11-04: Ferramentas e convenções da fundação (M0)

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

## 2026-11-04: Licença do código

Decisão: o código do repositório usa a Apache License 2.0, conforme o arquivo `LICENSE` já versionado. O `pyproject.toml` declara `license = "Apache-2.0"` e `license-files = ["LICENSE"]`. A licença cobre apenas o código. O corpus ConsumerBR, os dados derivados e os pesos treinados com ele seguem a licença do Zenodo, que G1 avalia. A aprovação da publicação do repositório continua pendente em G6.
Motivo: decisão do mantenedor. A Apache 2.0 é permissiva, inclui concessão explícita de patentes e já estava no repositório desde o commit inicial.
Alternativas: MIT; adiar a escolha até G6 e remover o `LICENSE` até lá.
Consequências: o README deixa de dizer que a licença será definida depois. O classificador `Private :: Do Not Upload` continua até G6. A publicação de modelos derivados do corpus não é autorizada por esta decisão; depende de G1.

## 2026-11-04: Pipeline de dados do M1

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

## 2026-11-04: Deduplicação e quase duplicatas

Decisão:

- Duplicatas exatas são definidas pelo SHA-256 do texto normalizado (NFC, minúsculas, espaços colapsados) e removidas no corpus inteiro, antes dos splits. Fica a ocorrência mais antiga. Linhas com data vencem as sem data.
- Quase duplicatas são marcadas com `loose_hash` (texto sem acentos, dígitos, pontuação e tags) no corpus inteiro, e não são removidas. O manifesto dos splits informa quantos grupos de `val`, `test` e `test_unseen_company` também aparecem em `train`.

Motivo: deduplicar antes do split garante que o mesmo texto nunca esteja em dois splits. O `loose_hash` mede quase duplicatas em todo o corpus pelo mesmo custo de uma amostra.

Alternativas: MinHash com LSH por amostragem, como o plano sugeria; remover também as quase duplicatas.

Consequências: paráfrases não são detectadas. Remover quase duplicatas fica para depois, se a medição mostrar que elas inflam as métricas.

## 2026-11-04: Empresas ocultas e janelas dos splits

Decisão:

- Uma empresa é oculta quando o SHA-256 de `<salt>:<nome normalizado>` cai abaixo de 5%. A decisão de cada empresa não depende das outras.
- Reclamações de empresas ocultas na janela de `test` formam `test_unseen_company`. As anteriores a 2024-07-01 ficam fora de todos os splits.
- O nome é normalizado com minúsculas, sem acentos e com espaços colapsados.
- As janelas comparam a data, sem hora, de `data_abertura`, com limites inclusivos.

Motivo: a regra por empresa dá o mesmo resultado no corpus completo e no `dev_sample`. Manter só a janela de `test` em `test_unseen_company` evita misturar generalização para empresas novas com generalização no tempo.

Alternativas: ordenar as empresas pelo hash e pegar exatamente 5%; incluir todas as reclamações das empresas ocultas em `test_unseen_company`.

Consequências: a fração de empresas ocultas é aproximada. Uma empresa muito grande sorteada como oculta reduz bastante o volume de `train`. O manifesto registra quantas empresas e linhas ficaram ocultas.

## 2026-11-04: Regras de urgência das diretrizes

Decisão: o mantenedor aprovou três regras de `docs/annotation_guidelines.md`:

- Telefonia e internet contam como serviço essencial. A interrupção no momento do relato leva a urgência `alta`. Instabilidade ou lentidão sem interrupção não conta.
- Na dúvida, o anotador escolhe o rótulo que julga mais provável e marca a dúvida. Não escolhe o nível mais alto por precaução.
- Negativação já feita é `media`. Ela só passa a `alta` com outro critério de `alta`, como prazo crítico ou vulnerabilidade relatada.

A lista de temas continua pendente até a leitura das 200 reclamações, que depende de G1. G2 fica parcial até lá.

Motivo: telecomunicações estão na lista de serviços essenciais da Lei 7.783/89, e uma regra simples evita dúvida na anotação. O gold set precisa refletir o texto. A meta de recall de urgência alta (>= 0,90) é garantida pelas regras de segurança da cascata, não por rótulos inflados. Negativação é um prejuízo em andamento, sem risco imediato por si só.

Alternativas: só água, energia, gás e saúde como essenciais; na dúvida, escolher o nível mais alto; negativação sempre `alta`.

Consequências: o gold set pode ter menos casos de `alta`. Se `gold_test` ficar com menos de 30, vale a regra do conjunto extra enriquecido (AGENTS.md, seção 7).

## 2026-11-04: Rótulos do M2: gold set, silver e camada de LLM

> Revisada pelas decisões de 2026-11-04 sobre a G1 e o Plano B, registradas abaixo: o texto do corpus não vai para a API da Anthropic, e os rótulos silver passam a ser gerados por um LLM local. O restante desta entrada continua valendo.

Decisão:

- **Camada de LLM antecipada.** `BatchLLMClient`, `FakeLLM`, o cache em disco, o registro de custo (`data/logs/llm_calls.jsonl`) e `configs/pricing.yaml` entram no M2, e não no M3, porque os rótulos silver precisam deles. Por enquanto só existe a interface de lote. O M3 acrescenta chamadas individuais para medir latência.
- **Cliente da Anthropic.** Message Batches API com structured outputs (`output_config.format`), `effort: low` e o prompt de sistema marcado para cache de prompt. Modelo: `LLM_MODEL_CHEAP` (Haiku 5.5). Preços conferidos na página oficial, com a data registrada em `configs/pricing.yaml`.
- **Conjuntos silver.** `silver_val` exclui os itens de `gold_dev`. Os itens de `gold_dev` recebem rótulos do LLM à parte (`gold_dev_llm`), só para medir a concordância com o gold.
- **Travas.** O cliente externo só roda com `ALLOW_EXTERNAL_LLM=true`, que deve ser ligado só depois de G1. Todo envio pago exige `CONFIRM_COST=1`. Acima do limite de aprovação, exige `APPROVED_USD` igual ou maior que a estimativa (G4). A estimativa somada ao que já foi gasto precisa caber em `LLM_BUDGET_USD`.
- **Cache e custo separados por backend.** Respostas do `FakeLLM` nunca substituem respostas reais e custam zero no orçamento. Cada rótulo silver grava o backend que o produziu.
- **Respostas inválidas** (JSON fora do schema, recusa, truncamento) são reenviadas uma vez. Se falharem de novo, ficam registradas com o motivo, sem rótulo.
- **Estimativa de custo** por heurística: 3,5 caracteres por token e 200 tokens de saída por item, sem o desconto do cache de prompt, para errar para cima. O manifesto compara estimativa e custo real.
- **Gold set.** O identificador do item é o `text_hash`. A fila é sorteada uma vez e não pode ser refeita depois do primeiro rótulo. Os 10% de reanotação são marcados na criação da fila. O gold é o rótulo da primeira rodada, e vale o último registro de cada rodada.
- **Ferramenta de anotação** em Streamlit (`ui/annotate.py`), antecipada da demo do M3. Novo alvo `make gold-report` e nova configuração `configs/labeling.yaml`.

Motivo: os rótulos silver são o primeiro gasto real do projeto e o primeiro envio de texto do corpus para fora. As travas tornam G1, G4 e o teto de custo verificáveis no código, e não só no processo. Excluir `gold_dev` de `silver_val` evita ajustar hiperparâmetros nos mesmos textos usados para avaliar.

Alternativas: chamadas individuais em vez de lotes (o dobro do preço); estimar tokens com o endpoint `count_tokens` (exige enviar o texto, ou seja, G1); deixar `gold_dev` dentro de `silver_val`; uma planilha no lugar da ferramenta de anotação.

Consequências: o M3 reaproveita a camada de LLM e precisa recusar rótulos com backend `fake` no treino. A estimativa pode errar, sobretudo nos tokens de raciocínio do Haiku 5.5. O primeiro lote real deve ser comparado com ela antes de qualquer lote maior.

## 2026-11-04: G1, licença do ConsumerBR

Decisão:

- Regra adotada: o que a licença não autoriza expressamente é tratado como não permitido.
- Pesquisa local (baixar, processar, treinar e avaliar na máquina do mantenedor): permitida. O texto restringe o uso a pesquisa e cita classificação de reclamações e geração de respostas.
- Envio de texto do corpus a API externa (LLM e agente de código): não permitido.
- Publicação de modelos derivados do corpus: não permitida.
- Exibição de casos reais na demo e no vídeo: não permitida. A demo usa `CASES_INDEX=synthetic`.
- Leitura adotada: a pesquisa local está coberta pelo texto. O que fica restrito é a publicação pública.
- Publicação pública: só código (Apache 2.0), métricas agregadas e fixtures sintéticas. Nunca dados, textos do corpus, índices nem pesos treinados. A aprovação da publicação do repositório continua em G6.
- Onde o corpus fica: o corpus real, os dados derivados e qualquer saída com texto ficam só na máquina do mantenedor. Treino em ambiente externo, como GPU na nuvem, também está fora. O agente de código roda em nuvem: trabalha só com dados sintéticos e vê apenas saídas agregadas (contagens, métricas, erros sem texto). A leitura das 200 reclamações para fechar a taxonomia (G2) é só do mantenedor.
- O Claude pode ser usado com texto que não vem do corpus: entrada sintética digitada na demo e o conjunto `redteam`, que é sintético. Isso não fere a regra 10.
- Os autores não serão consultados. A decisão se apoia apenas no texto disponível no Zenodo.
- A decisão é reversível. Se o texto completo da licença permitir o envio a API externa, o cliente da Anthropic já existe e é ativado com `ALLOW_EXTERNAL_LLM=true`.

Texto considerado, colado pelo mantenedor a partir do registro no Zenodo (`10.5281/zenodo.18022568`): direitos "Atribuição Creative Commons 4.0 Internacional" e "Licença de dados somente para pesquisa – ConsumerBR"; campos textuais anonimizados com marcadores padronizados e sem distribuição de textos brutos; tarefas previstas de classificação de reclamações e geração de respostas, entre outras; "O uso é restrito a fins acadêmicos e de pesquisa"; compromisso de não tentar reidentificação, não redistribuir os dados para fins não relacionados à pesquisa e cumprir a LGPD.

Motivo: o texto da licença não aborda API externa, modelos derivados nem exibição de casos. A restrição a "fins de pesquisa", a vedação de redistribuir fora da pesquisa e a LGPD tornam arriscado presumir permissão. Já a pesquisa local está expressamente prevista, com classificação de reclamações e geração de respostas entre as tarefas citadas.

Limite: o texto considerado parece ser a descrição do registro, e os termos completos do arquivo de licença não foram lidos. A CC BY 4.0 (permissiva) e a licença de dados somente para pesquisa (restritiva) parecem conflitar, e o texto não diz como se combinam. Seguem a regra "não permitido": envio de trechos anonimizados a API de terceiros, publicação de modelos treinados com o corpus, exibição de exemplos em demonstração ou vídeo. Ao ler os termos completos, o mantenedor pode revisar esta decisão aqui.

Alternativas: tratar a ausência de menção como permissão; ler o texto ao pé da letra e parar o projeto; consultar os autores; trocar a fonte de dados.

Consequências: o Claude sai de tudo que recebe texto do corpus (rótulos silver, C4 e C5, etapa de LLM da cascata, rascunhos com casos reais). A seção 20 do `AGENTS.md` foi aplicada na entrada seguinte.

## 2026-11-04: Plano B da G1: LLM de pesos abertos rodando localmente

Decisão: entre as opções da seção 20 do `AGENTS.md`, o projeto segue a opção A, LLM de pesos abertos rodando na máquina do mantenedor.

- **Cliente local atrás do `BatchLLMClient`**, como mais um backend com `is_external = False`. O cliente da Anthropic continua no código, bloqueado por `ALLOW_EXTERNAL_LLM=false`.
- **Modelos:** quatro candidatos de pesos abertos, escolhidos por triagem em `gold_dev` (entrada "Triagem dos LLMs locais para C4 e C5"). O ambiente de execução (por exemplo, Ollama, llama.cpp ou Transformers) vai para esta página quando for decidido. Gemini fica fora.
- **C4 e C5 passam a ser dois tamanhos de LLM local**, um menor e um maior, e respondem às mesmas perguntas: "quanto o LLM ganha sem treino?" e "mais computação melhora o resultado?".
- **Custo vira tempo de máquina e memória.** "Custo por 1.000 reclamações" passa a ser tempo de máquina e memória por 1.000, na mesma máquina. O ponto de equilíbrio é calculado em tempo de máquina, ou convertido em US$ com um hardware de referência declarado como premissa. Preços de API não se aplicam a texto do corpus, e `configs/pricing.yaml` fica sem uso com ele.
- **Rótulos silver pelo LLM local**, começando com um volume menor que o plano (2 mil a 5 mil), porque o tempo de geração local precisa ser medido antes de escalar. As curvas de aprendizado de 1.000, 5.000 e 20.000 rótulos continuam no plano, condicionadas a esse tempo.
- **O gold humano ganha peso.** A concordância entre os rótulos do LLM e `gold_dev` passa a ser critério de aceite do M2, e não só um relatório (entrada "Critério de concordância do silver com o `gold_dev`").
- **Cascata e rascunhos** usam o LLM local. A economia da cascata é medida em tempo e memória. Modelos menores escrevem pior em português, então validadores e abstenção pesam mais nos rascunhos.
- **Teto de US$ 30 e G4** só se aplicam se a API for liberada para texto do corpus.

Motivo: mantém o centro do projeto (comparar ML clássico, deep learning e LLM) sem enviar texto do corpus a terceiros. Com todos os modelos na mesma máquina, a medição de latência fica mais justa.

Alternativas: usar apenas rótulos humanos, em menor escala; trocar a fonte por uma base compatível com o uso.

Consequências:

- Exige uma máquina capaz de rodar um modelo de 7 a 8 bilhões de parâmetros, em geral com GPU ou com muita memória e quantização. O tempo de geração em CPU precisa ser medido, não presumido.
- Modelos locais precisam de geração restrita por schema ou de validação com retry. O reenvio de respostas inválidas do M2 continua útil.
- O prompt `classify/v1` foi escrito para o Claude e será ajustado em `gold_dev`, com nova versão registrada.
- Um LLM local pode ficar abaixo do Claude. Isso é um resultado válido e será reportado como tal, com a ressalva de que LLMs de API não foram avaliados com texto do corpus.
- O código do M2 (camada de LLM, `FakeLLM`, cache por backend, travas) continua correto. Falta o cliente local, a medição de tempo e memória no registro de chamadas e a troca da estimativa de custo pela estimativa de tempo nos jobs com texto do corpus.

## 2026-11-04: Triagem dos LLMs locais para C4 e C5

> O critério de viabilidade de C5 foi revisto na entrada "Ambiente do LLM local: Ollama, tags e camadas na CPU": parte das camadas pode ir para a CPU.

Decisão:

- C4 e C5 são um modelo cada. Quatro modelos de pesos abertos entram como candidatos de triagem, e no fim sobram dois: um para C4 e um para C5.

| Vaga           | Concorrentes                 | Quem decide                                                   |
| -------------- | ---------------------------- | ------------------------------------------------------------- |
| C4 (LLM menor) | Gemma 4 E4B × Qwen 3.5 4B    | Macro-F1 de tema no `gold_dev`, desempatando por velocidade   |
| C5 (LLM maior) | Qwen 3.5 9B × Llama 3.1 8B   | Macro-F1 de tema no `gold_dev` e viabilidade em 6 GB          |

- A triagem roda os quatro candidatos com o mesmo prompt, a mesma decodificação e a mesma máquina, sobre os 150 itens do `gold_dev`.
- **C4:** vence o maior macro-F1 de tema. Há empate quando o intervalo de 95% do bootstrap pareado (1.000 reamostragens) para a diferença de macro-F1 contém zero. No empate, vence o mais rápido, pela latência p50 por reclamação.
- **C5:** primeiro sai quem não roda em 6 GB, com a quantização escolhida e sem estourar a memória durante a triagem. Entre os que rodam, vence o maior macro-F1 de tema. Se nenhum rodar, C5 é cortado, como prevê a ordem de corte da seção 17 do `AGENTS.md`.
- O vencedor de C4 também gera os rótulos silver e `gold_dev_llm`, e é ele que passa pelo critério de concordância da entrada seguinte.
- A triagem registra, por candidato: macro-F1 de tema e de urgência com intervalos, recall de urgência alta, taxa de saídas válidas no schema, latência p50 e p95, vazão em lote, pico de memória e a quantização usada.
- O ambiente de execução (por exemplo, Ollama, llama.cpp ou Transformers) e a quantização ainda serão decididos, antes da triagem.

Motivo: dois tamanhos respondem às perguntas de C4 ("quanto o LLM ganha sem treino?") e de C5 ("mais computação melhora o resultado?"). Concorrentes de famílias diferentes em cada vaga evitam escolher por marca. O desempate de C4 por velocidade importa porque é o modelo que rotula o silver e alimenta a cascata. O limite de 6 GB vem do hardware disponível.

Alternativas: fixar um modelo por vaga sem triagem; triar todos os quatro para as duas vagas; decidir por acurácia em vez de macro-F1.

Consequências:

- A triagem depende do `gold_dev` anotado (G3) e do cliente do LLM local.
- O `gold_dev` é usado para ajustar o prompt, triar os modelos e medir a concordância do silver. As medidas nele são otimistas. A avaliação sem esse viés só acontece no `gold_test`, no M6.
- Os nomes e as versões exatas dos modelos (incluindo a quantização) entram nos manifestos e no MLflow de cada execução.

## 2026-11-04: Critério de concordância do silver com o `gold_dev` (aceite do M2)

Decisão:

- O M2 só é aceito se a concordância entre os rótulos silver e o `gold_dev` atingir o critério abaixo. O critério foi fixado antes de qualquer medição e não muda depois de ver os resultados. Qualquer mudança exige nova entrada neste arquivo.
- A concordância é medida entre os rótulos do LLM local escolhido para rotular o silver (`gold_dev_llm`) e os rótulos humanos de `gold_dev`.

| Métrica (silver × `gold_dev`)                                             | Aceite  | Alerta           | Reprova     |
| ------------------------------------------------------------------------- | ------- | ---------------- | ----------- |
| Kappa de tema (Cohen)                                                     | >= 0,60 | 0,50 a 0,59      | < 0,50      |
| Kappa de urgência (ponderado, pesos lineares, ordem baixa < media < alta) | >= 0,50 | 0,40 a 0,49      | < 0,40      |
| Recall de urgência alta (gold como referência)                            | só reportado | alerta se < 0,80 | não reprova |

- Decide o valor pontual. O intervalo de confiança de 95% (bootstrap de 1.000 reamostragens) é sempre reportado junto, com o número de casos por classe. O recall de urgência alta é reportado sempre com o seu número de casos.
- O critério vale para o agregado. A concordância por classe é só relatório, porque classes com menos de 5 exemplos são instáveis.
- Cada métrica cai na faixa correspondente. Vale a pior faixa entre tema e urgência.
- Ações por faixa:
  - Aceite: seguir para o silver em volume.
  - Alerta: seguir, registrar a limitação neste arquivo e explicar o viés no README e no relatório final (AGENTS.md, seção 7).
  - Reprova: nesta ordem, melhorar o prompt usando só o `gold_dev`; trocar o modelo de C4 entre os dois candidatos da triagem; reduzir a dependência do silver, treinando com menos silver e mais gold.
- O critério se aplica ao modelo escolhido na triagem de C4 (Gemma 4 E4B ou Qwen 3.5 4B).

Motivo: o silver treina os modelos locais, então rótulos ruidosos contaminam C1, C2 e C3. O kappa desconta a concordância por acaso, o que a acurácia não faz com 12 temas desbalanceados. A urgência é ordinal e tem mais zonas cinzentas, por isso o piso é menor. O recall de urgência alta só alerta, porque o `gold_dev` (150 itens) deve ter poucos casos e o intervalo de confiança será largo. Os valores são julgamento do mantenedor, apoiado em convenções (kappa de 0,6 a 0,8 costuma ser lido como concordância substancial), e não vêm de medição.

Alternativas: acurácia como métrica; critério mais rígido (kappa de tema >= 0,65); recall de urgência alta como condição de reprovação; critério definido depois de ver os resultados; pesos quadráticos no kappa de urgência, em vez de lineares.

Consequências:

- A medida é otimista, porque o prompt é ajustado no `gold_dev` e a concordância é medida nos mesmos itens. A concordância sem esse viés só aparece no `gold_test`, no M6. Isso fica registrado como limitação.
- Antes de fechar o critério, conferir o kappa da reanotação humana (10%, depois de 7 dias). A concordância do silver não deve ser exigida acima desse teto.
- Rótulos de LLM local menor tendem a ser mais ruidosos. A reprovação é um resultado possível e deve ser reportada como tal.
- O critério substitui, no aceite do M2, a frase "concordância silver contra `gold_dev` medida" (AGENTS.md, seção 17).
- Implementação: o `make gold-report` calcula hoje o kappa de Cohen simples (`labeling/agreement.py`). Faltam o kappa ponderado de urgência, o intervalo de confiança por bootstrap, o recall de urgência alta com o número de casos e a classificação em faixas.

## 2026-11-04: Treino e processamento só na máquina do mantenedor

Decisão: confirmada a regra da G1 de que treino e processamento com o corpus não podem usar ambiente externo, como GPU na nuvem. Isso inclui o treino de C3 (BERTimbau), que o plano antes permitia fora da máquina do mantenedor.

Motivo: a regra adotada na G1 trata como não permitido o que a licença não autoriza expressamente, e enviar o corpus a um serviço externo de computação não está autorizado.

Alternativas: treinar C3 em GPU na nuvem com dados anonimizados.

Consequências: C3 e os LLMs locais ficam limitados ao hardware do mantenedor. Se o treino de C3 ficar inviável, ele pode ser feito com menos dados ou menos épocas, e a limitação é reportada.

## 2026-11-04: Hardware da máquina do mantenedor

Decisão: a máquina do mantenedor, onde rodam o corpus, a triagem, os LLMs locais e os treinos, tem **6 GB de VRAM** e **32 GB de RAM**. O limite de 6 GB da triagem de C5 é de VRAM.

Motivo: o tamanho de modelo, a quantização e o ambiente de execução dependem desses números, e a triagem de C5 precisa de um critério verificável.

Alternativas: medir só na hora da triagem, sem registrar o hardware.

Consequências:

- Todas as medições de tempo, memória e latência são feitas nessa máquina e o relatório declara a configuração.
- Com 32 GB de RAM, um modelo que não cabe na VRAM ainda pode rodar com parte das camadas na CPU, mais devagar. O mantenedor confirmou que esse modo misto é aceito (entrada "Ambiente do LLM local").
- Os candidatos de C4 (cerca de 4 bilhões de parâmetros) devem caber na VRAM com quantização de 4 bits. Os de C5 (8 a 9 bilhões) ficam no limite, e a triagem decide.

## 2026-11-04: Convenções das métricas de avaliação (M3)

Decisão:

- O macro-F1 é a média simples do F1 de cada rótulo presente no gold ou nas previsões, como no padrão do scikit-learn. Um rótulo só previsto, nunca verdadeiro, entra com F1 zero.
- Os intervalos de 95% usam bootstrap por percentis, com 1.000 reamostragens e seed fixa. Comparações entre dois modelos usam as mesmas reamostragens para os dois (bootstrap pareado).
- Reamostragens em que a métrica fica indefinida (por exemplo, um kappa com uma só categoria) são descartadas e contadas no resultado.
- O kappa ponderado de urgência usa pesos de discordância lineares, |i - j| / (k - 1), na ordem baixa < media < alta. O kappa da reanotação humana é calculado do mesmo jeito, para servir de teto ao critério do silver.
- As métricas ficam em `src/customer_feedback_ai/evaluation/`, sem dependência nova. Foram conferidas contra o scikit-learn em 300 casos aleatórios, com diferença máxima de 3e-16.

Motivo: as métricas decidem a triagem, o aceite do M2 e a comparação de modelos, então a definição precisa estar escrita antes de qualquer resultado.

Alternativas: macro-F1 sobre todos os temas da taxonomia, inclusive os ausentes; intervalos por aproximação normal; usar o scikit-learn desde já.

Consequências: com poucos exemplos por tema no `gold_dev`, o macro-F1 oscila bastante, e os intervalos serão largos. Isso é reportado, não escondido.

## 2026-11-04: Ambiente do LLM local: Ollama, tags e camadas na CPU

Decisão:

- O LLM local roda no **Ollama**, na máquina do mantenedor (`http://localhost:11434`). O cliente usa `POST /api/chat` com saída restrita por JSON schema (`format`), `GET /api/ps` para medir quanto do modelo está na VRAM e `POST /api/show` para ler a quantização.
- Os candidatos são identificados pelas tags do Ollama, em minúsculas e com dois pontos, como o mantenedor passou:

| Vaga | Tag do Ollama  | Nome no plano |
| ---- | -------------- | ------------- |
| C4   | `gemma4:e4b`   | Gemma 4 E4B   |
| C4   | `qwen3.5:4b`   | Qwen 3.5 4B   |
| C5   | `qwen3.5:9b`   | Qwen 3.5 9B   |
| C5   | `llama3.1:8b`  | Llama 3.1 8B  |

- Quantização: as tags padrão do Ollama, com Q4_K_M esperada. A quantização real é lida do Ollama e gravada no manifesto de cada execução; se for diferente da esperada, o cliente avisa, mas não para.
- Decodificação igual para todos: temperatura 0, seed fixa, contexto de 4.096 tokens e `think: false`, que desliga o raciocínio dos modelos que pensam. Tudo fica em `configs/llm_local.yaml`.
- **Camadas na CPU são aceitas.** Nem todo modelo cabe inteiro nos 6 GB de VRAM, e parte das camadas pode rodar na CPU, com os 32 GB de RAM. Na triagem de C5, viável é o candidato que responde todos os itens do `gold_dev` na máquina sem erro de execução. A fração do modelo na VRAM é medida e registrada, mas não é exigida. Se nenhum candidato de C5 for viável, C5 é cortado.
- O vencedor de cada vaga é gravado em `chosen` no `configs/llm_local.yaml`, depois de registrado nesta página. Até lá, `make label-silver` exige `MODEL=<tag>` com um dos candidatos.

Motivo: o Ollama oferece saída restrita por schema, quantização pronta e a medida da VRAM usada, sem compilar nada na máquina do mantenedor. Exigir o modelo inteiro na VRAM eliminaria os candidatos de 8 e 9 bilhões de parâmetros nos 6 GB disponíveis, e o custo do modo misto aparece na latência, que já é medida.

Alternativas: llama.cpp via `llama-cpp-python`; Transformers com 4 bits; exigir o modelo inteiro na VRAM.

Consequências:

- O Ollama é um programa instalado à parte, fora do `uv.lock`. A versão do Ollama, a tag e a quantização de cada modelo vão para os manifestos.
- Um modelo com camadas na CPU fica mais lento, o que pesa na latência de C5 e no tempo da cascata. Isso é reportado como resultado.
- O silver usa o vencedor de C4. Com o LLM local, o job estima o tempo a partir das latências já medidas (a triagem mede primeiro) e registra o tempo real no manifesto, com custo zero.
- `think: false` vale para todos os modelos. Se algum não aceitar o parâmetro, o erro aparece na primeira chamada, e o valor `null` em `configs/llm_local.yaml` deixa o padrão do modelo.

## 2026-11-04: Execução da triagem dos LLMs (`make llm-triage`)

Decisão:

- A triagem usa os 150 itens do `gold_dev` com rótulo humano da primeira rodada. Com o `gold_dev` incompleto, o comando recusa. A opção `--allow-incomplete` existe só para rodadas de teste, e o relatório as marca como não válidas para a escolha.
- Cada candidato recebe primeiro uma chamada de aquecimento, com texto sintético, que carrega o modelo e fica fora das medidas. Depois, cada reclamação é uma chamada individual.
- Uma resposta inválida é reenviada uma vez. Se continuar inválida, conta como erro na métrica e nunca vira uma classe: o macro-F1 usa os rótulos do gold e os rótulos válidos previstos.
- **Viável** é o candidato sem falha de execução em nenhuma chamada (por exemplo, falta de memória). Resposta inválida não tira a viabilidade, porque já pesa no macro-F1.
- **C4:** um candidato não viável é desclassificado, porque o vencedor de C4 rotula o silver. Com os dois viáveis, vale a regra do intervalo pareado e da latência p50.
- **C5:** um empate exato no macro-F1 de tema também vai para a menor latência p50, e o relatório diz que houve empate.
- As respostas válidas vão para o cache por backend, com a mesma chave do job de silver. Assim, os itens do `gold_dev` não são rotulados de novo no silver. Uma nova rodada da triagem reaproveita o cache e a latência original. `--fresh` (ou `make llm-triage FRESH=1`) mede tudo de novo.
- Saídas, sem texto de reclamação:
  - `data/reports/llm_triage.json`, com métricas e intervalos, validade das respostas, latência p50 e p95, vazão, tempo de carga, quantização, fração na VRAM e a escolha sugerida;
  - `data/gold/triage/<tag>.parquet`, com as previsões por item;
  - o manifesto `llm_triage`;
  - o registro de chamadas, que depois dá ao `make label-silver` a estimativa de tempo.
- O pipeline só recomenda. O mantenedor registra a escolha nesta página e preenche `chosen` em `configs/llm_local.yaml`.
- A latência da triagem vem de 150 chamadas. A medida final de latência do M3 (passo 9) usa pelo menos 200 reclamações, como pede o plano.
- O registro no MLflow fica para o passo 6, junto com os primeiros treinos, para que todos os experimentos entrem no MLflow do mesmo jeito.

Motivo: a escolha de C4 e C5 precisa ser reproduzível e explicável, e o aquecimento evita que o tempo de carregar o modelo distorça a latência do primeiro item.

Alternativas: contar a resposta inválida como uma classe; aceitar um C4 com falhas de execução; medir a latência incluindo o carregamento; escrever o vencedor direto na configuração.

Consequências: a triagem depende do `gold_dev` completo (G3). Com dois candidatos muito próximos, a decisão de C4 tende ao empate e, portanto, à velocidade.


## 2026-11-04: Modelos locais B0, B1 e C1 e registro no MLflow (`make train-local`)

Decisão:

- **Entrada:** todos os modelos recebem só `reclamacao_labeled`. A lista de colunas passa pela mesma checagem de vazamento dos dados (`check_classifier_inputs`) e vai para o MLflow e o relatório.
- **Treino e ajuste:** os modelos treinam no `silver_train` e se ajustam no `silver_val`. O `gold_dev` só avalia, quando já tem rótulos humanos. O `test` não é lido.
- **B0:** prevê sempre o tema e a urgência mais frequentes do `silver_train`. Num empate, vence o rótulo que vem primeiro em ordem alfabética, para o resultado não depender da ordem das linhas.
- **B1:** regras de palavras-chave em `configs/rules.yaml`, versão `v1`.
  - O agente escreveu as regras a partir da taxonomia e das diretrizes de anotação, sem ver texto do corpus (G1).
  - A comparação ignora caixa e acentos. Os temas são testados em ordem fixa, e vence o primeiro que casar. Sem casamento, o tema é `outro`.
  - Urgência: `alta` se aparecer um termo da lista de alta, `baixa` se aparecer um da lista de baixa, `media` nos demais casos.
  - B1 não aprende com rótulos. Um teste garante que as regras só usam temas da taxonomia.
- **C1:** um vetorizador TF-IDF de palavras (1 e 2 gramas) e caracteres (3 a 5 gramas, `char_wb`), ajustado só no `silver_train`, compartilhado por duas regressões logísticas, uma para tema e outra para urgência.
  - As duas usam `class_weight=balanced`, porque a métrica principal é o macro-F1.
  - A regularização `C` vem da grade em `configs/train.yaml` e é escolhida no `silver_val` pelo macro-F1, separadamente para cada saída. Num empate, fica o `C` menor, que regulariza mais.
  - Por isso os números de C1 no `silver_val` são otimistas, e o relatório avisa. O `gold_dev` é a medida comparável.
- **Curvas de aprendizado:** `--train-size n` (ou `TRAIN_SIZE=n`) usa os `n` primeiros itens do `silver_train` em ordem de hash do texto. Isso se comporta como uma amostra aleatória fixa, e as amostras ficam aninhadas: as 1.000 estão dentro das 5.000, que estão dentro das 20.000.
- **Medições** (a parte de memória foi substituída na revisão abaixo, "Revisão do B1, da medição de memória e dos números do `silver_val`"):
  - tempo de treino (relógio do `fit`);
  - memória de pico durante o treino e a inferência, medida pelo `tracemalloc` (heap do Python, que inclui os buffers do NumPy e do SciPy). Não é a memória total do processo, e o relatório final declara isso;
  - tamanho do artefato salvo;
  - latência p50 e p95 com chamadas individuais em 300 reclamações do `silver_val`, depois de uma chamada de aquecimento.

  A comparação final com os LLMs, na mesma máquina e com o mesmo método, é o passo 9.
- **Rótulos do `FakeLLM`:** o treino recusa. A opção `--allow-fake-labels` existe só para rodadas de teste com dados sintéticos, que ficam marcadas como `valid=false` no relatório, no manifesto e no MLflow.
- **MLflow:** `mlflow-skinny`, com registro em SQLite em `<DATA_DIR>/mlflow/mlflow.db`, sem servidor.
  - O MLflow 3 recusa o armazenamento em arquivos (`mlruns/`) sem uma variável de ambiente, por isso o SQLite. `sqlalchemy` e `alembic` entram como dependências dele.
  - Os artefatos do MLflow, se houver, ficam em `<DATA_DIR>/mlflow/artifacts/`, nunca dentro do repositório.
  - A telemetria do MLflow fica desligada, porque o projeto não contata serviços externos sem necessidade.
  - Cada execução registra: commit e estado do repositório, SHA-256 dos arquivos de entrada, backend e modelo dos rótulos, hiperparâmetros e escolhas do treino, métricas no `silver_val` e no `gold_dev`, tempo, memória, tamanho e latência.
  - A triagem dos LLMs (`make llm-triage`) também passa a registrar uma execução por candidato, como previa a decisão da triagem.
  - Para ver as execuções: `uvx mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db`. O `uvx` baixa o MLflow completo num ambiente à parte, fora do `uv.lock`.
- **Saídas:**
  - `<DATA_DIR>/models/<run_id>/`, com os modelos treinados, que nunca são publicados (G1);
  - `<DATA_DIR>/reports/train_local.json`, só com números agregados;
  - o manifesto `train_local`.

  O `reports/metrics.json` versionado e o `make report` vêm depois, com os resultados reais.

Motivo: os baselines e o C1 são o piso e a referência clássica da comparação. Ajustar só no silver mantém o `gold_dev` como medida independente para o mesmo critério dos LLMs.

Alternativas:

- escolher o `C` no `gold_dev`;
- usar um vetorizador por saída;
- `mlflow` completo ou armazenamento em arquivos;
- medir a memória pelo RSS do processo;
- regras do B1 geradas por LLM ou ajustadas olhando os erros no `gold_dev`.

Consequências:

- O B1 é deliberadamente simples. Se o mantenedor revisar as regras depois da leitura das 200 reclamações (G2), deve aumentar a versão em `configs/rules.yaml`, que vai para o manifesto. Ajustar as regras olhando os erros no `gold_dev` deixaria o B1 otimista.
- A memória pelo `tracemalloc` subestima bibliotecas que alocam fora do Python. No passo 9, a comparação com os LLMs precisa de uma medida comum (por exemplo, o RSS de pico em processo separado), e a escolha fica registrada.

## 2026-11-04: Revisão do B1, da medição de memória e dos números do `silver_val`

Decisão:

- **B1, regras versão 0.2.0.** A revisão das regras contra a taxonomia e as diretrizes achou casamentos errados, que foram corrigidos:
  - A comparação passa a ser por palavra inteira. Um termo terminado em `*` é um radical (`negativ*` casa "negativado"), sempre a partir do início de uma palavra. Antes, `uti` casava "utilizei" e dava urgência alta, e `sac` casava "transação" e "sacar".
  - `tratamento` saiu da urgência alta, porque "péssimo tratamento do atendente" é comum. Ficaram `tratamento medico` e `tratamento de saude`.
  - `endereco` saiu de `dados_cadastro`, porque aparece muito em queixas de entrega.
  - `cartao de credito` saiu de `credito_negativacao`. Ele vinha antes de `cobranca_indevida` e pegava cobranças no cartão, que pela regra de desempate são cobrança.
  - `produto_defeito` passou para antes de `entrega_atraso`, como manda o desempate ("chegou com defeito"). As palavras de entrega ficaram mais específicas (`nao chegou`, `atraso na entrega`, `rastreio`...), e `entrega` sozinha saiu.
  - A urgência alta ganhou `sem internet`, `sem sinal` e `sem telefone`, porque as diretrizes contam telefonia e internet como serviços essenciais, além de `aviso de corte`, `ameaca de corte` e `urgencia`.
  - Os casos acima viraram testes, com frases inventadas.
- **Memória medida em processo separado.** O `tracemalloc` saiu, por dois motivos: ele não enxerga a memória alocada fora do Python (PyTorch, no C2 e no C3), e o rastreamento deixava o `fit` mais lento enquanto o tempo de treino era medido.
  - Depois do treino, um processo novo, só com CPU, carrega o modelo salvo e classifica as reclamações do `silver_val` uma por chamada. Ele mede o tempo de carga, a latência p50 e p95, o tempo de CPU por 1.000 reclamações e o pico de memória residente (RSS).
  - **Memória do modelo** é o pico do processo menos a memória antes de carregar o modelo, com as bibliotecas que o modelo importa (scikit-learn, PyTorch). Os imports são preguiçosos, então o B0 não paga pelo PyTorch.
  - No Linux, o pico vem do `VmHWM` (`/proc/self/status`), não do `ru_maxrss`. Um processo filho herda no `ru_maxrss` o pico do pai: num teste, o filho de um processo com 400 MB alocados mostrou 411 MB pelo `ru_maxrss` e 10 MB pelo `VmHWM`. No macOS, o pico vem do `ru_maxrss`; no Windows, fica vazio. O relatório registra o método.
  - A memória do treino deixa de ser medida, porque o plano pede memória de inferência. O C3 registra o pico de memória da GPU.
  - Para os LLMs (passo 9), a memória vem do Ollama (RAM e VRAM do modelo carregado), já que o modelo roda no processo do servidor. A forma de pôr as duas medidas lado a lado fica para o passo 9.
- **Números do `silver_val`.** O ajuste continua no `silver_val`, como o plano define para hiperparâmetros e early stopping: regularização do C1 e do C2, e early stopping do C3. Assim, os três modelos ajustáveis têm o mesmo tratamento. Os números deles no `silver_val` são otimistas e servem só para acompanhar o ajuste. A comparação entre modelos usa o `gold_dev`, e o relatório diz isso nos campos `comparison_set` e `tuned_on_silver_val`. No C1, o otimismo tende a ser pequeno, porque a grade tem três valores.

Motivo: as regras do B1 precisam ser simples, mas não erradas por detalhe de implementação. A memória precisa ser comparável entre modelos de bibliotecas diferentes. O `gold_dev` é o único conjunto que nenhum modelo usou para ajuste.

Alternativas:

- manter a busca por trecho, com listas de exceções;
- medir a memória pelo RSS do processo principal;
- escolher a regularização por validação cruzada no `silver_train`, que custaria várias vezes o treino do C3 e se afastaria do plano.

Consequências:

- A memória do C2 e do C3 inclui o PyTorch, que sozinho ocupa centenas de MB. Esse é o custo real de operar esses modelos.
- A taxonomia descreve `credito_negativacao` com "cartão de crédito", e o desempate manda cobranças para `cobranca_indevida`. Fica a sugestão para o G2: deixar claro quais assuntos de cartão entram em crédito (por exemplo, limite, anuidade ou contratação).

## 2026-11-04: C2 e C3 (passo 7)

Decisão:

- **Dependências:** PyTorch, Transformers e Sentence Transformers ficam no extra opcional `deep`, instalado com `make setup DEEP=1`.
  - O pacote do PyTorch para Linux traz as bibliotecas CUDA e ocupa vários GB, então a CI roda sem ele. Os testes do C2 e do C3 são pulados lá e rodam onde o extra está instalado.
  - O mypy trata essas bibliotecas como `Any`, com ou sem elas instaladas, para dar o mesmo resultado na CI e na máquina do mantenedor.
  - Sem o extra, pedir C2 ou C3 para com uma mensagem que diz como instalar.
- **Pesos dos modelos base:** o Serafim e o BERTimbau são baixados do Hugging Face na máquina do mantenedor. Só os pesos públicos descem; nenhum texto do corpus sai da máquina (G1). O campo `revision` em `configs/train.yaml` fixa um commit. Vazio, usa o mais recente, e o commit baixado é registrado.
- **C2:** embeddings do Serafim sem fine-tuning, normalizados, com uma regressão logística por saída e a regularização escolhida no `silver_val`, como no C1.
  - O modelo salvo inclui uma cópia do encoder e carrega sem download.
  - O relatório conta quantos textos passam do limite de tokens do encoder, que os corta.
- **C3:** BERTimbau com duas cabeças lineares sobre o vetor `[CLS]`, treinadas juntas com a soma das duas entropias cruzadas. As classes são balanceadas como no C1.
  - Configuração inicial: truncamento em 256 tokens, AdamW com taxa de 2e-5 e weight decay de 0,01, aquecimento em 10% dos passos com decaimento linear, até 3 épocas, recorte do gradiente em 1,0 e lote de 16.
  - O treino usa fp16 na GPU. Espera-se que lote de 16 com 256 tokens caiba em 6 GB; se faltar memória, reduza o lote e aumente `grad_accumulation`.
  - Early stopping: guarda a época com o melhor macro-F1 de tema no `silver_val` e para depois de uma época sem melhora (`patience: 1`).
  - Depois do treino, o modelo vai para a CPU, onde a qualidade e o custo de inferência são medidos.
  - O relatório registra quantos textos foram cortados em 256 tokens no `silver_train` e no `silver_val`, as épocas rodadas, a melhor época, o dispositivo, a GPU e o pico de memória dela. Com GPU, o tempo de treino é o tempo de GPU.
  - As seeds são fixas, mas os kernels da GPU não são deterministas bit a bit, então dois treinos podem diferir um pouco.
  - Os pesos ajustados derivam do corpus e ficam em `<DATA_DIR>/models/`. Nunca são publicados (G1).

Motivo: o C2 responde se embeddings prontos valem a dependência, e o C3, se treinar um transformer compensa. Os dois seguem o mesmo protocolo dos demais modelos: mesmas entradas, ajuste no `silver_val`, comparação no `gold_dev` e inferência medida em CPU.

Alternativas:

- PyTorch como dependência obrigatória;
- o `Trainer` do Transformers, que esconde o laço de treino e traz dependências extras;
- fine-tuning também no C2;
- uma cabeça só, com as classes de tema e urgência combinadas.

Consequências:

- O treino real do C3 depende da GPU da máquina do mantenedor, e os hiperparâmetros são um ponto de partida, a confirmar pelo early stopping e pelo tempo medido.
- A comparação de truncamento em 512 tokens pode ser feita mudando `max_length`, mas não faz parte do plano inicial.
- Os embeddings do Serafim são recalculados a cada treino. Um cache pode vir com a recuperação (M5), que usa o mesmo encoder.
