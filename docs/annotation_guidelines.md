# Diretrizes de anotação

Status: **rascunho, G2 parcial.** As regras de urgência foram aprovadas pelo mantenedor em 2026-11-10 (`docs/decisions.md`). A lista de temas em `configs/taxonomy.yaml` ainda pode mudar depois da leitura das 200 reclamações de `make taxonomy-sample`.

Todos os exemplos deste documento são inventados. Nenhum vem do corpus.

## 1. O que anotar

Cada reclamação recebe dois rótulos:

- `topic`: um único tema da taxonomia.
- `urgency`: `baixa`, `media` ou `alta`.

Use apenas o texto da reclamação (`reclamacao_labeled`). Não consulte a empresa, a resposta, o status, a nota ou qualquer outro campo, nem a saída de modelos. Os classificadores recebem só o texto, então o rótulo também deve depender só dele.

## 2. Procedimento

1. Leia a reclamação inteira antes de decidir.
2. Identifique o **pedido principal**: o que a pessoa quer que a empresa faça.
3. Escolha o tema desse pedido, usando as regras de desempate da seção 4.
4. Avalie a urgência pelos critérios da seção 5, com base no que está relatado. Não tente verificar se é verdade.
5. Se ficar em dúvida, escolha o rótulo que julga mais provável, marque o campo de dúvida da ferramenta e escreva o motivo em poucas palavras. Não escolha o nível mais alto só por precaução: o gold set mede o que está no texto, e a segurança de urgência é papel das regras da cascata.

A anotação é cega: a ferramenta não mostra a empresa, nenhuma saída de modelo nem rótulos anteriores. Ela é aberta com `make annotate` e grava cada rótulo em `data/gold/annotation/labels.jsonl`. Para corrigir um item, anote de novo: vale o último rótulo. `make gold-report` exporta `gold_dev` e `gold_test` e mostra o progresso, o kappa da reanotação e os alertas da seção 7.

## 3. Temas

| Tema                   | Use quando o pedido principal é sobre                                                           |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| `cobranca_indevida`    | Cobrança, débito ou fatura que a pessoa não reconhece ou contesta                               |
| `cancelamento`         | Cancelar produto, serviço, plano ou assinatura, quando o cancelamento não foi atendido          |
| `reembolso_estorno`    | Receber de volta dinheiro já pago, por estorno ou reembolso                                     |
| `entrega_atraso`       | Produto não entregue, atrasado, extraviado ou trocado na entrega                                |
| `produto_defeito`      | Produto com defeito, avaria ou diferente do anunciado, incluindo troca e garantia               |
| `servico_indisponivel` | Serviço contratado interrompido, instável ou não prestado                                       |
| `fraude_golpe`         | Golpe, fraude, transação ou contratação feita por terceiros, uso indevido de dados              |
| `oferta_contrato`      | Oferta, publicidade ou contrato descumprido, condições alteradas, venda casada, reajuste        |
| `atendimento`          | Falha do atendimento como queixa principal: falta de resposta, demora, desrespeito              |
| `dados_cadastro`       | Erro, alteração ou exclusão de cadastro e pedidos sobre dados pessoais                          |
| `credito_negativacao`  | Negativação, score, empréstimo, financiamento, cartão de crédito ou renegociação de dívida      |
| `outro`                | Nenhum dos anteriores                                                                           |

## 4. Regras de desempate

Reclamações costumam ter vários assuntos. Use o pedido principal e, se ainda houver dúvida, estas regras:

| Conflito                                        | Regra                                                                                                   |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `cancelamento` x `cobranca_indevida`            | Se a pessoa quer encerrar o contrato, `cancelamento`. Se o contrato já foi encerrado e só a cobrança continua, `cobranca_indevida`. |
| `cobranca_indevida` x `reembolso_estorno`       | Se o dinheiro já saiu da conta e a pessoa quer de volta, `reembolso_estorno`. Se contesta uma cobrança ainda em aberto, `cobranca_indevida`. |
| `cobranca_indevida` x `fraude_golpe`            | Se a pessoa diz que a compra ou o contrato foi feito por outra pessoa, `fraude_golpe`.                   |
| `cobranca_indevida` x `credito_negativacao`     | Se o centro é o nome negativado, o score ou um empréstimo, `credito_negativacao`.                        |
| `cobranca_indevida` x `oferta_contrato`         | Se a pessoa cita um preço ou condição prometidos que não foram cumpridos, `oferta_contrato`.             |
| `entrega_atraso` x `produto_defeito`            | Produto que não chegou ou chegou trocado: `entrega_atraso`. Chegou com defeito ou avariado: `produto_defeito`. |
| `produto_defeito` x `servico_indisponivel`      | Bem físico: `produto_defeito`. Serviço contínuo, como internet, energia ou conta digital: `servico_indisponivel`. |
| `atendimento` x qualquer tema                   | `atendimento` só quando a falha no atendimento é a queixa em si. Se ela agrava outro problema, use o tema do problema. |
| Vários pedidos com o mesmo peso                 | Use o primeiro pedido feito no texto.                                                                    |
| Texto ilegível, vazio ou sem pedido             | `outro`, com dúvida marcada.                                                                             |

Exemplos inventados:

- "Pedi o cancelamento em março e continuo recebendo boleto." Pedido: parar a cobrança de um contrato que já deveria estar encerrado. Tema: `cobranca_indevida`.
- "Quero cancelar o plano e o atendente não deixa." Tema: `cancelamento`.
- "Apareceram três compras no cartão que eu não fiz." Tema: `fraude_golpe`.
- "Abri cinco chamados e ninguém respondeu sobre a minha troca." O pedido é a troca. Tema: `produto_defeito`.

## 5. Urgência

Avalie o que está relatado no texto. Basta um critério de `alta` presente para marcar `alta`.

### `alta`

- **Risco à saúde ou à vida:** tratamento, exame ou medicamento negado ou atrasado com relato de necessidade urgente, equipamento médico sem energia, alimento ou produto que causou dano à saúde.
- **Fraude em andamento:** transações ou acessos não reconhecidos que ainda podem continuar, como cartão ou conta ainda ativos.
- **Interrupção de serviço essencial:** água, energia elétrica, gás, serviços de saúde, telefonia ou internet, quando o serviço está interrompido no momento do relato. Telefonia e internet contam como essenciais, como na lista de serviços essenciais da Lei 7.783/89. Instabilidade ou lentidão sem interrupção não conta.
- **Prazo crítico:** dano iminente com data próxima, como viagem, cirurgia, prova, prazo judicial ou corte anunciado.
- **Vulnerabilidade relatada:** idoso, criança, pessoa com deficiência, doença grave ou falta de renda para necessidades básicas, quando ligada ao problema.

### `media`

Prejuízo financeiro ou de serviço que ainda está acontecendo, sem os sinais de `alta`. Exemplos: cobrança indevida em aberto, produto pago e não entregue, nome negativado, serviço não essencial interrompido.

**Negativação já feita** é `media`. Ela só passa a `alta` quando o texto traz outro critério de `alta`, como um prazo crítico (financiamento negado com data próxima) ou uma vulnerabilidade relatada.

### `baixa`

Insatisfação sem prejuízo em andamento nem prazo próximo. Exemplos: problema já resolvido que a pessoa quer registrar, pedido de informação, reclamação sobre a qualidade do atendimento sem outro dano.

Exemplos inventados:

- "Estou sem energia há dois dias e meu pai usa oxigênio em casa." `alta` (saúde, serviço essencial e vulnerabilidade).
- "Fui cobrado duas vezes na fatura deste mês." `media`.
- "Estou sem internet desde ontem e não consigo trabalhar." `alta` (serviço essencial interrompido).
- "Meu nome foi negativado por uma dívida que já paguei." `media`.
- "Fui negativado por engano e o financiamento da casa vence na sexta." `alta` (prazo crítico).
- "O atendente foi grosseiro, mas o problema já foi resolvido." `baixa`.

## 6. Casos especiais

- **Tags de anonimização** como `[NOME]` e `[EMAIL]` são parte do texto. Não tente adivinhar o que escondem.
- **Reclamação sobre outra empresa** que não a reclamada: anote o tema normalmente. A ferramenta não mostra a empresa.
- **Texto muito curto** ("Não resolveram"): `outro` e `baixa`, com dúvida marcada, a menos que o texto traga um tema claro.

## 7. Qualidade da anotação

- **Reanotação:** 10% da amostra é anotada de novo pelo menos 7 dias depois, sem ver o primeiro rótulo. Reportamos o kappa de Cohen intra-anotador, separado para tema e urgência.
- **Classes raras:** se um tema tiver menos de 5 exemplos em `gold_dev`, a taxonomia é revisada antes de anotar `gold_test`, e a decisão vai para `docs/decisions.md`.
- **Urgência alta rara:** se `gold_test` tiver menos de 30 casos de `alta`, criamos um conjunto extra por busca de palavras-chave, com anotação cega, reportado separadamente.
- **Mudanças nas diretrizes** depois do início da anotação geram nova versão deste documento e da taxonomia, e os casos afetados são revistos.
