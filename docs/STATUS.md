# Status

Atualizado em: 2026-11-04
Marco ativo: M3, Comparação de modelos. As decisões de entrada estão registradas: G1, plano B com LLM local, triagem de C4 e C5, critério do silver e treino só na máquina do mantenedor. M1 e M2 têm o código pronto, e o aceite depende de passos do mantenedor (ver "Pendências de aceite").
Último commit na `main`: `e916f2c` (docs: revise plan and status for local LLMs and M3). O passo 1 do M3 aguarda revisão e commit do mantenedor.

## Decisões em vigor (2026-11-04)

- **G1:** a pesquisa local é permitida. Não são permitidos: enviar texto do corpus a API externa (LLM e agente de código), publicar modelos derivados, exibir casos reais na demo ou no vídeo, e treinar ou processar em ambiente externo. A publicação pública fica limitada a código, métricas agregadas e fixtures sintéticas (G6).
- **Plano B, opção A:** os LLMs da comparação, dos rótulos silver, da cascata e dos rascunhos são de pesos abertos e rodam localmente. Custo é medido em tempo de máquina e memória.
- **Triagem de C4 e C5:** quatro candidatos, dos quais sobram dois.

  | Vaga           | Concorrentes               | Quem decide                                                 |
  | -------------- | -------------------------- | ----------------------------------------------------------- |
  | C4 (LLM menor) | Gemma 4 E4B × Qwen 3.5 4B  | Macro-F1 de tema no `gold_dev`, desempatando por velocidade |
  | C5 (LLM maior) | Qwen 3.5 9B × Llama 3.1 8B | Macro-F1 de tema no `gold_dev` e viabilidade em 6 GB        |

  O vencedor de C4 também rotula o silver.
- **Critério do silver (aceite do M2):** kappa de tema de pelo menos 0,60 (alerta de 0,50 a 0,59) e kappa ponderado de urgência, com pesos lineares, de pelo menos 0,50 (alerta de 0,40 a 0,49). O recall de urgência alta é só reportado, com alerta abaixo de 0,80. Vale o valor pontual, com intervalo de 95% por bootstrap sempre ao lado, e vale a pior faixa entre tema e urgência.
- **Ambiente externo:** treino e processamento com o corpus só na máquina do mantenedor, inclusive o C3.
- **Hardware:** 6 GB de VRAM e 32 GB de RAM. O limite de 6 GB da triagem de C5 é de VRAM.
- **Métricas:** macro-F1 sobre os rótulos presentes no gold ou nas previsões, bootstrap por percentis com 1.000 reamostragens, bootstrap pareado nas comparações e kappa ponderado linear na urgência.
- **Agente de código:** roda em nuvem, então trabalha só com dados sintéticos e vê apenas saídas agregadas, sem texto.
- Registros completos em `docs/decisions.md`. `AGENTS.md`, README, `docs/data_card.md` e `docs/annotation_guidelines.md` estão alinhados com essas decisões.

## Concluído

### M0, Fundação: aceito

- `make lint typecheck test` passa.
- A CI no GitHub Actions executou os mesmos comandos com sucesso em todos os pushes da `main`, até `a9b391e`.
- G1 respondida e registrada.

### M1, Dados e taxonomia: código pronto

- Ingestão, limpeza, deduplicação, splits temporais com empresas ocultas, manifestos, EDA, `dev_sample` e amostra para a taxonomia, testados com dados sintéticos.
- O pipeline gera saídas idênticas com a mesma entrada, e os testes provam que os splits não se sobrepõem.
- G2 parcial: as regras de urgência foram aprovadas. A lista de temas espera a leitura das 200 reclamações.

### M2, Rótulos: código pronto

- Fila do gold set, ferramenta de anotação cega (`make annotate`), reanotação após 7 dias e relatório com kappa e alertas (`make gold-report`).
- Camada de LLM (`BatchLLMClient`, `FakeLLM`, cache por backend, registro de chamadas sem texto, travas de G1 e custo) e job de rótulos silver (`make label-silver`), testados com o `FakeLLM`.
- O cliente da Anthropic continua no código, bloqueado por `ALLOW_EXTERNAL_LLM=false`, como a G1 exige.
- Evidência: `make lint typecheck test` com 187 testes aprovados, na `main` e na CI.

### M3, Comparação de modelos: em andamento

- **Passo 1, avaliação: concluído.** O módulo `src/customer_feedback_ai/evaluation/` traz:
  - métricas: macro-F1, F1 por classe, acurácia, recall de um rótulo, kappa de Cohen e kappa ponderado (linear ou quadrático);
  - intervalos de 95% por bootstrap e bootstrap pareado para diferenças;
  - o critério do silver em faixas (aceite, alerta, reprova) com o aviso de teto da reanotação humana;
  - as regras da triagem de C4 (empate pelo intervalo pareado, depois latência p50) e de C5 (limite de VRAM, depois macro-F1).
- **`make gold-report`:** passa a aplicar o critério do silver. Mostra a faixa, os valores com intervalos, os suportes e o recall de urgência alta, e marca como inválido para o M2 qualquer resultado com rótulos do `FakeLLM`. A reanotação humana ganhou o kappa ponderado de urgência.
- **Configuração:** os limiares do critério estão em `configs/labeling.yaml` (`silver_criterion`), com os valores da decisão.
- **Evidências:**
  - `make lint typecheck test`: Ruff sem erros, mypy strict sem erros em 74 arquivos, 221 testes aprovados (34 novos).
  - Valores conferidos à mão nos testes, por exemplo o kappa ponderado de 5/7 (linear) e 0,8 (quadrático) para o mesmo par de sequências.
  - Comparação com o scikit-learn em 300 casos aleatórios (macro-F1, kappa, kappa ponderado linear e quadrático, recall): diferença máxima de 3e-16. O scikit-learn foi usado só nessa conferência e não virou dependência.

## Pendências de aceite

| Marco | Critério                                                       | Situação                                  | Responsável |
| ----- | -------------------------------------------------------------- | ----------------------------------------- | ----------- |
| M1    | Pipeline no corpus real e divergências do artigo documentadas  | pendente                                  | mantenedor, na própria máquina, enviando só agregados |
| M1    | G2: lista de temas aprovada                                    | parcial                                   | mantenedor  |
| M2    | G3: `gold_dev` e `gold_test` anotados, com reanotação de 10%   | pendente                                  | mantenedor  |
| M2    | Silver gerado pelo vencedor de C4, com tempo estimado e real   | depende do cliente local e da triagem (M3) | agente e mantenedor |
| M2    | Concordância do silver com `gold_dev` na faixa de aceite ou alerta | critério definido; medição pendente   | agente (cálculo) e mantenedor (execução) |

## Próximo passo: plano do M3

O agente desenvolve tudo com dados sintéticos. Treinos, triagem e avaliações reais rodam na máquina do mantenedor, que repassa só métricas e contagens.

| Passo | Entrega                                                                                                                       | Depende de                           | Quem |
| ----- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ---- |
| 1 ✅  | **Avaliação (concluído):** módulo `evaluation/` com macro-F1 de tema e de urgência, F1 por classe, recall de urgência alta, bootstrap pareado com 1.000 reamostragens, intervalos de 95% e kappa ponderado. O `make gold-report` passa a mostrar a faixa do critério do silver. | nada                                 | agente |
| 2     | **Ambiente do LLM local:** comparar Ollama, llama.cpp e Transformers quanto a saída restrita por schema, quantização, medição de memória e instalação. A escolha e a quantização vão para `docs/decisions.md` e `configs/llm_local.yaml`. | hardware definido (6 GB de VRAM, 32 GB de RAM); proposta do agente pendente de decisão | agente propõe, mantenedor decide |
| 3     | **Cliente do LLM local:** backend atrás do `BatchLLMClient`, com `is_external = False`, saída restrita por schema ou validação com retry, e tempo e memória por chamada no registro. `make label-silver` passa a usá-lo por padrão, com estimativa de tempo no lugar da estimativa de custo. O treino recusa rótulos do `FakeLLM`. | passo 2                              | agente |
| 4     | **`make llm-triage`:** roda os quatro candidatos no `gold_dev` e aplica as regras de escolha (macro-F1, empate pelo intervalo do bootstrap pareado, latência p50, limite de 6 GB). Grava as métricas e o MLflow. | passos 1 e 3; `gold_dev` anotado (G3) | agente constrói, mantenedor executa e registra a escolha |
| 5     | **Silver com o vencedor de C4:** medir o tempo por reclamação, gerar de 2 mil a 5 mil rótulos e aplicar o critério de concordância. Fecha o M2. | passo 4                              | mantenedor executa |
| 6     | **B0, B1 e C1:** classe majoritária, regras com palavras-chave e TF-IDF com regressão logística (dois classificadores), com MLflow. | passo 1 (código); passo 5 (treino real) | agente |
| 7     | **C2 e C3:** Serafim com regressão logística e BERTimbau com duas cabeças, testando o truncamento em 256 tokens. | passo 6                              | agente constrói, mantenedor treina |
| 8     | **C4 e C5 e curvas:** avaliação dos dois LLMs escolhidos em `gold_dev`, com prompt versionado, e curvas de aprendizado com 1.000, 5.000 e 20.000 rótulos, conforme o tempo medido. | passos 4 e 5                         | mantenedor executa |
| 9     | **Medições e demo:** latência p50 e p95, tempo de máquina e memória por 1.000, tamanho do artefato e ponto de equilíbrio em tempo de máquina. Primeira versão de `make demo`, com classificação lado a lado e índice sintético. | passos 6 a 8                         | agente |

O passo 1 está pronto. O próximo é o passo 2, que depende da escolha do ambiente de execução. Em paralelo, o mantenedor pode:

- rodar `make data sample splits taxonomy-sample` no corpus;
- concluir G2;
- anotar `gold_dev` com `make annotate`;
- escolher o ambiente de execução do LLM local.

## Bloqueios

- Ambiente de execução e quantização do LLM local não definidos. O agente propõe Ollama com quantização de 4 bits (mantenedor decide).
- Falta confirmar se "viabilidade em 6 GB" exige o modelo inteiro na VRAM, que é a proposta do agente, ou aceita parte das camadas na CPU, já que há 32 GB de RAM (mantenedor).
- G2 parcial e G3 pendente (mantenedor). O `gold_dev` anotado é pré-requisito da triagem.
- O formato real do CSV ainda não foi visto. Se divergir, `make data` para e aponta a coluna, e o ajuste é feito em `configs/data.yaml` (mantenedor e agente).
- Os termos completos da licença não foram lidos. A G1 pode ser revista se eles permitirem mais usos (mantenedor).
