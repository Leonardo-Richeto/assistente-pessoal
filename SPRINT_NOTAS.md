# Sprint — notas de passagem (arquivo temporário)

> Lido no começo de toda sessão e escrito durante ela. O plano e a tabela de
> passos ficam em `SPRINT.md`. Sai do repo quando a sprint fechar.

## Onde estamos

- **Sprint 1 (Etapa A, teste no MacBook):** Passo 1 feito (2026-10-16).
- **Próximo:** Passo 2, Tier B, Sonnet 5.5, effort médio, autopilot.
- **Última atualização:** 2026-10-16, Haiku 5.5 (executor do Passo 1), MacBook Air.

## Avisos vivos

- O MacBook é um Air M1 com 8 GB (arm64). O build da imagem roda em arm64; o
  i7 vai rodar em amd64.
- O Docker Desktop está instalado (`/Applications/Docker.app`) e o daemon sobe com
  `open -a Docker`.
- `uv` 0.13.1 instalado com Homebrew em 2026-10-16. Python do projeto: 3.14.2.
- O `gh` (GitHub CLI) não está instalado. O clone foi por HTTPS; o push precisa
  de credencial do GitHub no git.
- `AUTH_DESATIVADA` só serve para teste local sem Funnel. Nunca ligue o Funnel
  com o login desligado.
- `docker-compose.yml` não repassa `AUTH_DESATIVADA` ao serviço `servidor`.
  O Passo 2 precisa acrescentar a linha (ver o prompt).
- O build Docker e o OAuth real nunca rodaram (a Fase 0 foi escrita no app do
  Claude, sem Docker).

## Passos feitos

### Preparação (2026-10-16, Opus 5.5, Claude Code no MacBook)

- **Fez:** clonou o repo; leu `CONTEXTO.md`, `PLANO.md`, `docs/IMPLANTACAO.md`
  e o código (819 linhas); criou `SPRINT.md` e este arquivo; ligou
  `CLAUDE.md` e `CONTEXTO.md` a eles.
- **Verificado:** só o ambiente (comandos acima). Testes não rodaram: falta `uv`.
- **Pendente para o Leonardo:**
  1. As fases 2 a 5 vão rodar no MacBook antes do i7, ou o i7 entra logo depois
     da Etapa A? O `docs/IMPLANTACAO.md` diz i7 logo depois.
- **Achado para o Passo 3:** `BLOQUEADAS` em `servidor/assistente/servidor.py`
  usa nomes que ninguém conferiu contra as versões fixadas das peças prontas.

### Passo 1 — Ambiente local (2026-10-16, Haiku 5.5, executor)

- **Fez:** subiu o daemon do Docker (respondeu em menos de 5 s); instalou `uv`
  0.13.1 com `brew install uv`; rodou `uv sync` e `uv run pytest` em
  `servidor/`; marcou A1, A2 e A3 em `docs/IMPLANTACAO.md`; status do Passo 1
  em `SPRINT.md` para Feito.
- **Verificado:** `docker compose version` = Docker Compose v5.3.1;
  `uv run pytest` = `17 passed in 6.01s` (Python 3.14.2, pytest 9.1.1; 12
  testes em `tests/test_auth.py`, 5 em `tests/test_banco.py`).
- **Não verificado:** o build Docker não rodou (é o Passo 2).
- **Achado:** `docker-compose.yml` não repassa `AUTH_DESATIVADA` ao serviço
  `servidor`.

## Prompt do próximo passo

> **Passo 2 — Stack local sem internet.** Tier B · Sonnet 5.5 · effort médio · autopilot.
>
> **Objetivo:** subir a stack no MacBook (arm64) com Postgres, migração e
> servidor MCP em `http://127.0.0.1:8000`, e provar com um smoke que registrar,
> consultar, desfazer e auditar funcionam. Sem Funnel e sem login real.
>
> **Leia antes:** `SPRINT.md` (linha do Passo 2), este arquivo, `CLAUDE.md`,
> `docs/IMPLANTACAO.md` (A7 e A8), `docker-compose.yml`, `.env.example`,
> `servidor/assistente/config.py`, `servidor/assistente/servidor.py`,
> `servidor/alembic/` (migrações).
>
> **Faça:**
> 1. Confirme `docker info` respondendo. Se não responder, rode `open -a Docker` e espere até 2 min.
> 2. Crie `.env` na raiz (é git-ignorado) com:
>    - `SENHA_DONO`, `SENHA_LEITURA`, `SENHA_ESCRITA` e `JWT_SIGNING_KEY`, cada uma gerada por `openssl rand -base64 32`. Não imprima os valores.
>    - `PUBLIC_BASE_URL=http://127.0.0.1:8000`
>    - `AUTH_DESATIVADA=true` (campo `auth_desativada` em `config.py`).
>    - `AUTH_PROVEDOR=github`; `VAULT_PATH`, `PAPERLESS_URL` e `PAPERLESS_API_KEY` vazios.
> 3. Em `docker-compose.yml`, no serviço `servidor`, em `environment`, acrescente
>    `AUTH_DESATIVADA: ${AUTH_DESATIVADA:-false}`. Confira com `docker compose config`.
> 4. Confirme que o compose publica a porta só em `127.0.0.1:${PORTA_HOST:-8000}:8000`.
>    Se não publicar, corrija, sem expor `0.0.0.0`.
> 5. Rode `docker compose up -d --build`. Se o build falhar, guarde o log em
>    `SPRINT_NOTAS.md` e corrija só Dockerfile ou compose (arm64). Não mude código de produção.
> 6. Confira a migração: o serviço `migracao` sai com código 0. Depois rode
>    `docker compose exec postgres psql -U assistente_dono -d assistente -c '\dt'` e confirme as tabelas.
> 7. Confira o servidor: `docker compose logs servidor` e
>    `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/mcp` (não pode ser 5xx).
> 8. Escreva um smoke com `fastmcp.Client` em `http://127.0.0.1:8000/mcp`, fora do repo
>    (pasta de scratchpad). Liste as ferramentas com `client.list_tools()` e use os nomes reais.
>    Registre um gasto; consulte e ache o gasto; desfaça; consulte de novo e confirme
>    que sumiu da lista ativa; confira a tabela `Auditoria` com as operações.
> 9. Rode `cd servidor && uv run pytest` e confirme 17 testes passando.
>
> **Não faça:** não ligue Tailscale nem Funnel. Não crie `.env` de produção
> nem use senhas de exemplo. Não rode `docker compose down -v` sem aviso antes.
> Não faça push. Não imprima valores de segredo em saída, log ou arquivo.
> Não altere código de produção além do que o build exigir.
>
> **Pronto quando:** postgres saudável, migração com código 0, servidor
> respondendo em 127.0.0.1:8000, smoke passando nas quatro etapas e 17 testes
> passando. Marque A7 (parcial: `.env` local, sem credenciais GitHub) e A8 em
> `docs/IMPLANTACAO.md`. Marque o Passo 2 como Feito no `SPRINT.md`. Escreva o
> bloco do Passo 2 em "Passos feitos" e atualize "Onde estamos". Reescreva esta
> seção com o prompt do Passo 3 (Opus 5.5, alto, supervisionado): conferir os
> nomes das ferramentas bloqueadas do `mcpvault@0.16.0` e do `paperless-mcp==0.1.0`
> contra `BLOQUEADAS` em `servidor/assistente/servidor.py`. Commit com a linha
> `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`. Sem push.
