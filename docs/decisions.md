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
| G2  | Fim do M1                             | pendente | -    | -        |
| G3  | Durante o M2                          | pendente | -    | -        |
| G4  | Antes de job LLM acima do limite      | pendente | -    | -        |
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
