# Sprint — notas de passagem (arquivo temporário)

> Lido no começo de toda sessão e escrito durante ela. O plano e a tabela de
> passos ficam em `SPRINT.md`. Sai do repo quando a sprint fechar.

## Onde estamos

- **Sprint 1 (Etapa A, teste no MacBook):** Passos 1 e 2 feitos (2026-10-16).
- **Stack rodando** no MacBook: postgres, servidor em `127.0.0.1:8000`, `AUTH_DESATIVADA=true`.
- **Próximo:** Passo 3, Tier A, Opus 5.5, effort alto, supervisionado (sem commit).
- **Última atualização:** 2026-10-16, Sonnet 5.5 (executor do Passo 2), MacBook Air.

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
- O build Docker passou no arm64 (Passo 2). O OAuth real nunca rodou.
- `uv` local usa Python 3.14.2; a imagem usa Python 3.12.15. Um teste que passa
  local pode falhar na imagem (e o contrário). Rode comandos de ferramentas
  dentro do container quando o resultado depender da versão.
- O `.venv` local ganhou o flag `hidden` do macOS (2026-10-16, 12:10). O Python 3.14
  ignora `.pth` escondido e o pytest falha com `No module named 'assistente'`.
  Correção: `chflags -R nohidden servidor/.venv`.
- `.env` local é de teste (senhas geradas, `AUTH_DESATIVADA=true`, URL
  `http://127.0.0.1:8000`). Não serve para produção. O Passo 5 reescreve.
- O banco já tem 2 gastos de smoke (ids 1 e 2, desfeitos) e 4 linhas de
  auditoria. Apague o volume (`docker compose down -v`) só com aviso ao Leonardo.

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

### Passo 2 — Stack local sem internet (2026-10-16, Sonnet 5.5, executor)

- **Fez:** criou `.env` local (senhas hex e `JWT_SIGNING_KEY` geradas com openssl,
  nada impresso; `git check-ignore .env` = `.env`); acrescentou `AUTH_DESATIVADA`
  ao serviço `servidor` no compose; subiu a stack; rodou o smoke; marcou A7
  (parcial) e A8; status do Passo 2 = Feito.
- **Correções de infra (2 achados do build real):**
  1. `deploy/postgres/01-papeis.sh` sem bit de execução: o postgres apresentava
     `bad interpreter: Permission denied`, pulava a criação dos papéis e o
     healthcheck passava, mas o `assistente_leitura`/`escrita` não existiam.
     Correção: `chmod +x` (o git guarda o modo; vale no i7). O volume
     criado nessa tentativa estava vazio e foi apagado com `down -v` (sem dado).
  2. `servidor/Dockerfile`: `uv tool install` gravava em `/root/.local/share/uv`
     (modo 700) e o usuário `assistente` não executava `paperless-mcp`
     (`Permission denied`). Correção: `UV_TOOL_DIR=/opt/uv-tools`. Verificado:
     `paperless-mcp --help` roda como usuário `assistente`.
- **Verificado:**
  - `docker compose up -d --build` (arm64): build ok; `migracao` saiu com 0.
  - `\dt`: `alembic_version`, `atividades`, `auditoria`, `gastos`, `ponto`.
  - Porta publicada só em `127.0.0.1:8000->8000/tcp`.
  - `curl http://127.0.0.1:8000/mcp` = 400 (sem cabeçalho MCP; não é 5xx).
  - Log do servidor mostra o aviso "AUTH DESATIVADA".
  - Smoke: 5 etapas OK (ver abaixo). Linhas conferidas no banco.
  - `uv run pytest` = 17 passed (após `chflags nohidden`).
- **Não verificado:** login real e Funnel (Passos 4 e 5); `mcpvault` e
  `paperless-mcp` montados pelo servidor (VAULT_PATH e PAPERLESS_* vazios);
  build em amd64.
- **Smoke (para repetir):** script fora do repo, em
  `/private/tmp/claude-501/-Users-leonardoricheto-Desktop-Projetos-assistente-pessoal/11cd4c36-6ae3-4f96-a50e-935ec27f3b21/scratchpad/smoke.py`.
  Rode com `cd servidor && uv run python <caminho>`. Ele abre `fastmcp.Client`
  em `http://127.0.0.1:8000/mcp`, lista as ferramentas, chama `registrar_gasto`
  (12.34, categoria `teste`), `consultar_gastos` (acha), `desfazer_registro`,
  `consultar_gastos` (sumiu) e `consultar_auditoria` (as duas operações). Sai
  com código 1 na primeira falha. Se a pasta de scratchpad sumir, recrie o
  script com esses passos.
- **Ferramentas expostas hoje (só banco):** `consultar_atividades`,
  `consultar_auditoria`, `consultar_gastos`, `consultar_ponto`,
  `desfazer_registro`, `listar_categorias_gasto`, `registrar_atividade`,
  `registrar_gasto`, `registrar_ponto`.

## Prompt do próximo passo

> **Passo 3 — Conferir as ferramentas bloqueadas.** Tier A · Opus 5.5 · effort alto · **supervisionado**.
>
> **Objetivo:** descobrir os nomes reais das ferramentas do `@bitbonsai/mcpvault@0.16.0`
> e do `paperless-mcp==0.1.0`, compará-los com `BLOQUEADAS` em
> `servidor/assistente/servidor.py` e deixar o bloqueio correto e testado.
> Nome errado em `BLOQUEADAS` deixa uma ferramenta perigosa ligada sem aviso.
>
> **Leia antes:** `SPRINT.md` (linha do Passo 3), este arquivo (avisos vivos e
> bloco do Passo 2), `CLAUDE.md` (regra: ferramenta irreversível ou que expõe
> dados vai para `BLOQUEADAS`), `servidor/assistente/servidor.py`,
> `servidor/Dockerfile`, `servidor/tests/` (estilo dos testes).
>
> **Contexto:**
> - A stack está rodando (`docker compose ps`). A imagem já tem `mcpvault` e
>   `paperless-mcp` em `/usr/local/bin`, na versão fixada, com Python 3.12.
> - O servidor monta cada peça com `namespace="vault"` ou `"paperless"`. O
>   FastMCP junta namespace e nome com `_`: a ferramenta `delete_note` do
>   mcpvault aparece como `vault_delete_note`. Confirme esse formato na prática.
>   `BLOQUEADAS` usa os nomes já com prefixo e é aplicada por `app.disable(names=...)`.
> - `.env` local tem `VAULT_PATH` e `PAPERLESS_*` vazios, então hoje nenhuma das
>   duas peças está montada. Não grave segredo em lugar nenhum.
>
> **Faça:**
> 1. Liste as ferramentas reais de cada peça (nome, descrição, annotations,
>    parâmetros). Duas formas aceitas; use as duas se der, para cruzar:
>    - Direto, sem o servidor: dentro do container
>      (`docker compose exec servidor ...`) ou na imagem
>      (`docker compose run --rm --no-deps servidor ...`), rode um script curto
>      com `fastmcp.Client` por stdio. Exemplo `mcpvault`:
>      `StdioTransport(command="mcpvault", args=["/tmp/vaultfalso"])` com uma
>      pasta temporária vazia. Exemplo Paperless: `command="paperless-mcp",
>      args=["--stdio"]` com `PAPERLESS_URL=http://127.0.0.1:1` e
>      `PAPERLESS_TOKEN=x` de mentira (a listagem não precisa de Paperless real;
>      se o binário exigir conexão para listar, registre e use o código-fonte
>      instalado em `/opt/uv-tools/paperless-mcp`).
>    - Pelo proxy: monte `criar_app` com `vault_path` apontando para uma pasta
>      temporária e `paperless_url`/`paperless_api_key` de mentira, e chame
>      `list_tools()` com `fastmcp.Client(app)`. Isso mostra os nomes com prefixo
>      e prova qual `disable` pegou.
>    Guarde as listagens completas em `SPRINT_NOTAS.md` (nomes e uma linha por
>    ferramenta; sem dado real).
> 2. Compare com `BLOQUEADAS`. Para cada um dos seis nomes atuais, diga se
>    existe, com o nome exato. Corrija os que não existem para o nome real.
> 3. Avalie cada ferramenta restante e decida se entra na lista. Critério
>    (de `CLAUDE.md`): irreversível (apaga, sobrescreve sem volta, move de modo
>    que não se reverte), ou expõe dados para fora (link público, upload para
>    terceiro, exportação, acesso a arquivo fora do vault). Atenção especial a:
>    - mcpvault: apagar, mover/renomear, editar em lote, escrever fora das notas,
>      qualquer coisa que aceite caminho absoluto ou `..` (confirme se o limite
>      à pasta do vault vale).
>    - paperless-mcp: apagar, editar em lote, juntar/dividir, reprocessar, links
>      de compartilhamento, mudar permissões, excluir tags/correspondentes.
>    Ferramenta de leitura e de criação reversível fica ligada. Em dúvida, bloqueie
>    e registre o motivo.
> 4. Escreva o teste em `servidor/tests/` (ex.: `test_bloqueadas.py`) que:
>    - falha se algum nome de `BLOQUEADAS` não existir nas peças. Como as peças
>      são processos externos, use a lista de nomes reais capturada no item 1
>      como fixture (constante no teste, com a versão no comentário) ou, se for
>      estável e rápido, suba o binário por stdio com pasta temporária. O teste
>      não pode depender de Paperless real, internet ou de `docker`.
>    - confirma que cada nome bloqueado sai de `list_tools()` do app montado.
>    - confirma que as ferramentas de leitura essenciais continuam visíveis.
>    Rode o teste e prove que ele falha com um nome errado (troque um nome,
>    veja falhar, volte).
> 5. Edite só `BLOQUEADAS` (e, se preciso, o comentário acima dela) em
>    `servidor/assistente/servidor.py`. Não altere outra lógica.
> 6. Se mudar `servidor.py`, reconstrua e confira a stack:
>    `docker compose up -d --build`, depois o smoke do Passo 2 (ver o bloco dele).
> 7. Rode `cd servidor && uv run pytest` e informe o total. Lembre: o `uv` local usa
>    Python 3.14 e a imagem usa 3.12. Se o teste depender de binários, rode-o também
>    dentro do container (`docker compose run --rm --no-deps servidor ...`, só se
>    o pytest existir na imagem; a imagem usa `--no-dev`, então avise se não existir).
> 8. Atualize `SPRINT_NOTAS.md`: bloco do Passo 3 em "Passos feitos", "Onde
>    estamos" e, na tabela do `SPRINT.md`, Passo 3 = Feito **só depois** do ok
>    do Leonardo. Reescreva esta seção com o prompt do Passo 4 (Tier D: o
>    Leonardo faz Tailscale e GitHub OAuth App; o modelo guia, linha
>    IMPLANTACAO A4 a A6).
>
> **Não faça:**
> - **Não faça commit e não faça push.** Deixe tudo no working tree.
> - Não ligue Tailscale, Funnel nem login real. Não use dado real do vault ou do Paperless.
> - Não religue nenhuma ferramenta bloqueada. Não crie ferramenta de SQL livre.
> - Não imprima nem grave segredo.
> - Não mude código de domínio (`banco.py`, `db.py`, `auth.py`, migrações).
>
> **Pronto quando:** `BLOQUEADAS` só tem nomes que existem, com prefixo certo;
> as ferramentas irreversíveis ou que expõem dados estão todas na lista, cada
> uma com motivo em comentário; o teste novo passa e se prova capaz de falhar;
> a suíte inteira passa; a stack segue rodando. Responda ao orquestrador com:
> 1. resultado em uma frase;
> 2. tabela "peça / nome real / estava em BLOQUEADAS? / decisão / motivo";
> 3. o diff descrito (arquivos e linhas), pronto para o orquestrador mostrar ao
>    Leonardo, com a lista das ferramentas que continuam ligadas;
> 4. comandos rodados e resultado real (listagens, pytest, smoke);
> 5. o que não verificou e o risco.
> O Leonardo aprova o diff; só então o orquestrador manda commitar com a linha
> `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push.
