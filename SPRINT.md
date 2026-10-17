# Sprint — plano e passos (arquivo temporário)

> Arquivo temporário da sprint. Sai do repo quando a sprint fechar, depois de
> consolidado em `CONTEXTO.md` e no vault. Regras do vault:
> `sprint-com-um-passo-por-sessao-e-modelo` e `registro-temporario-de-sprint-na-raiz`.
> A passagem entre sessões fica em `SPRINT_NOTAS.md`.

## O que é o projeto

Assistente pessoal do Leonardo. O app do Claude (iPhone, Mac, web) é a porta de
entrada. Ele conversa com um servidor MCP que roda em casa, com login pelo Google
(decisão do Leonardo, 2026-10-17; o GitHub continua no código como alternativa). O servidor guarda gastos, ponto e diário num Postgres, e dá acesso ao
Paperless e ao vault. Os dados ficam em casa; o modelo é só o cérebro.

O plano é testar tudo no MacBook Air M1 (8 GB) e, quando estiver estável,
passar para o i7 dedicado.

## Fontes de verdade

1. `CONTEXTO.md`: histórico, decisões, premissas e máquinas.
2. `README.md`: arquitetura e princípios.
3. `PLANO.md`: fases e tarefas do produto.
4. `docs/IMPLANTACAO.md`: Etapa A (MacBook) e Etapa B (i7), com `[x]`.
5. `CLAUDE.md`: regras de código que não se negociam.

Se este arquivo divergir de uma fonte acima, vale a fonte. Corrija este arquivo.

## Regras da sprint

1. Uma sessão faz um passo. Rode `/clear` entre os passos.
2. O modelo precisa estar no tier do passo ou acima. Modelo acima usa o effort
   do passo. Modelo abaixo para e avisa.
3. Nunca use effort max.
4. **Supervisionado:** o Leonardo acompanha e aprova o que toca login,
   exposição à internet ou dado real. **Autopilot:** o modelo roda sozinho.
5. **Tier D** é do Leonardo: conta, segredo, exposição à internet, dinheiro.
   O modelo guia e confere; não faz por ele.
6. Leia `SPRINT_NOTAS.md` antes de tudo. Anote nele durante a sessão.
7. Ao terminar: testes passando, `[x]` em `docs/IMPLANTACAO.md` ou `PLANO.md`,
   status na tabela abaixo, bloco novo em `SPRINT_NOTAS.md` e commit (sem push).
8. Segredo nunca entra nestes arquivos nem no git.
9. **Orquestração:** por padrão, uma sessão do Opus roda cada passo como
   subagente, com o modelo e o effort do passo, e confere antes de seguir.
   Ela para no Tier D e quando um passo falha.
10. O prompt completo do próximo passo fica em `SPRINT_NOTAS.md` § Prompt do
    próximo passo. Quem termina um passo reescreve essa seção.

## Tiers

| Tier | Tipo de trabalho | Modelo | Effort |
|---|---|---|---|
| **A** | login, exposição, segurança, schema, dado | Opus 5.5 | alto |
| **B** | lógica ou infraestrutura com contrato definido | Sonnet 5.5 | médio |
| **C** | mecânico, conferência, docs | Haiku 5.5 | baixo |
| **D** | ação do Leonardo (conta, segredo, internet) | o modelo só guia | — |

## Sprint 1 — Etapa A: teste no MacBook

| Passo | O que é | Tier | Modelo | Effort | Modo | Depende de | Status |
|---|---|---|---|---|---|---|---|
| 1 | Ambiente local: abrir o Docker Desktop, instalar `uv` (`brew install uv`), `uv sync`, `uv run pytest` (17 testes). IMPLANTACAO A1–A3 | C | Haiku 5.5 | baixo | autopilot | — | Feito |
| 2 | Stack local sem internet: `.env` de teste com senhas geradas, `docker compose up -d --build` no M1 (arm64), migração aplicada, smoke com `fastmcp.Client` contra `127.0.0.1:8000` (registrar, consultar, desfazer, auditoria). Corrigir Dockerfile/compose se o build falhar. Parte do A8 | B | Sonnet 5.5 | médio | autopilot | 1 | Feito |
| 3 | Conferir as ferramentas bloqueadas: listar os nomes reais das ferramentas do `mcpvault@0.16.0` e do `paperless-mcp==0.1.0` e comparar com `BLOQUEADAS`. Nome errado deixa ferramenta perigosa ligada. Cobrir com teste | A | Opus 5.5 | alto | supervisionado | 2 | Feito; mais 3 bloqueadas a pedido do Leonardo (2026-10-17); revisor passou |
| 4 | Tailscale no Mac (HTTPS + Funnel, `tailscale funnel --bg 8000`) e cliente OAuth do Google de teste. IMPLANTACAO A4–A6 | D | Leonardo (Sonnet 5.5 guia) | baixo | supervisionado | 2 | Feito 2026-10-17 (Leonardo, guiado pelo Opus 5.5) |
| 5 | Login real: `.env` com `PUBLIC_BASE_URL`, `AUTH_PROVEDOR=google` e credenciais do passo 4, subir, conferir `/.well-known/oauth-protected-resource/mcp` = 200, sem token = 401, e-mail fora da lista = recusado. Conector no claude.ai. IMPLANTACAO A7–A9 | A | Opus 5.5 | alto | supervisionado | 3, 4 | Feito 2026-10-17 (Opus 5.5); A9 conectado pelo Leonardo; revisor passou |
| 5b | Correções do revisor dos Passos 3–5: lista de permitidas nas peças, limite por IP em `/register` e `/authorize`, prazo de clientes no volume oauth, testes de `/authorize` e do tokeninfo, redirects somam ao padrão, parâmetros de escrita conferidos, categorias sem desfeitos, sem checagem no PyPI | A | Opus 5.5 | alto | supervisionado | 5 | Feito 2026-10-17; commit do orquestrador |
| 5c | Correções do revisor do 5b: lista de permitidos na troca do código por token (conta fora da lista não recebe token), limite em `/consent`, `/token` e `/auth/callback`, teto global por caminho, prazo de cliente sem token de 1 dia, redirects só https e sem curinga, avisos de log sem inundar | A | Opus 5.5 | alto | supervisionado | 5b | Feito 2026-10-17; commit do orquestrador |
| 6 | Teste ponta a ponta pelo iPhone: gasto → consultar → desfazer; ponto → horas. Conferir no banco as linhas e a auditoria. IMPLANTACAO A10 | C | Haiku 5.5 | baixo | supervisionado | 5 | Feito 2026-10-17 (Leonardo + Opus 5.5 orquestrador) |
| 7 | Vault com uma **cópia** em `VAULT_PATH`: ler, buscar, criar nota; apagar continua bloqueado. IMPLANTACAO A11 | B | Sonnet 5.5 | médio | supervisionado | 6 | Pendente |
| 8 | Projeto "Assistente" no claude.ai com instruções de uso (PLANO 1.6). O texto é de produto: vira ficha "proposta" antes | B | Sonnet 5.5 | médio | supervisionado | 6 | Pendente |
| 9 | Usar alguns dias e anotar o que faltou em `docs/IMPLANTACAO.md` (A12) | D | Leonardo | — | — | 6 | Pendente |
| 10 | Fechar a sprint: consolidar em `CONTEXTO.md` e no vault, apagar `SPRINT.md` e `SPRINT_NOTAS.md` com o ok do Leonardo | C | Haiku 5.5 | baixo | supervisionado | 9 | Pendente |

## Sprint 2 — Etapa B: produção no i7 (planejar em detalhe quando a Sprint 1 fechar)

| Passo | O que é | Tier | Modelo | Effort |
|---|---|---|---|---|
| B1 | Inventário de todas as máquinas, com SMART → vault + `docs/inventario.md` | C | Haiku 5.5 | baixo |
| B2–B4 | Debian/Ubuntu Server, Docker, Git, clone, Tailscale Funnel no i7 | D | Leonardo (Sonnet 5.5 guia) | baixo |
| B5–B7 | OAuth App de produção, `.env` com senhas novas, subir a stack | A | Opus 5.5 | alto |
| B8–B9 | Conector de produção no claude.ai e testes do A10 | C | Haiku 5.5 | baixo |
| B10 | Levar os registros do teste ou começar limpo | D | Leonardo | — |

## Fases seguintes do `PLANO.md` (cada fase vira uma sprint)

Tarefa com ⚑ no plano é Tier A. O resto segue a regra abaixo.

| Fase | Tarefas | Tier padrão |
|---|---|---|
| 2 Documentos e vault | 2.1 Paperless (B), 2.2 vault no i7 + Syncthing (D + B), 2.3 commit diário (C), ⚑ 2.4 envio de arquivos (A) | B |
| 3 Workers | 3.1 pacote de workers (B), 3.2 Pluggy manual (D), 3.3 worker Pluggy idempotente (A: dado financeiro), 3.4 conciliação (B) | B |
| 4 Agenda | 4.1 conector nativo (D), 4.2 tabela + sync (A: schema) | A |
| 4b E-mail | 4b.1 conector nativo (D), ⚑ 4b.2 e-mail multi-conta (A), 4b.3 envio (A) | A |
| 5 Rotinas | 5.1 tarefa agendada (C), 5.2 `resumo_periodo` (B) | B |
| 6 WhatsApp | ⚑ 6.1 desenho (A), 6.2–6.5 (B) | B |
| 7 Backup | 7.1 rotina (B), 7.2 teste de restauração (A) | A |

## Prompt de abertura

Para abrir um passo à mão, sem orquestrador. Cole numa sessão nova do Claude
Code, na pasta do projeto, com o modelo e o effort da tabela. Troque só o número
do passo. O detalhe do passo vem de `SPRINT_NOTAS.md` § Prompt do próximo passo.

```
Leia SPRINT.md e SPRINT_NOTAS.md na raiz, depois CONTEXTO.md, CLAUDE.md e
docs/IMPLANTACAO.md. Execute só o Passo N da Sprint 1.
Confira se você está no tier do passo; se estiver abaixo, pare e avise.
Anote em SPRINT_NOTAS.md durante a sessão. Ao terminar: testes passando,
[x] no IMPLANTACAO/PLANO, status na tabela do SPRINT.md, bloco do passo em
SPRINT_NOTAS.md ("Onde estamos" atualizado) e commit sem push.
```
