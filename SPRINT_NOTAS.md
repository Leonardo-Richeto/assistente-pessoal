# Sprint — notas de passagem (arquivo temporário)

> Lido no começo de toda sessão e escrito durante ela. O plano e a tabela de
> passos ficam em `SPRINT.md`. Sai do repo quando a sprint fechar.

## Onde estamos

- **Sprint 1 (Etapa A, teste no MacBook):** Passos 1 a 7, 5b, 5c, 8b, 8b2 e 8b3 feitos. Passo 8: ficha 1 aprovada
  (commit `e02afb4`); falta criar o Projeto no claude.ai. 8b e 8b2 no commit `5f12b86`. Os arquivos do Passo 8b3
  estão no working tree, sem commit: o orquestrador confere, roda o revisor e faz o commit.
- **Pendente do Leonardo (Passo 8b3):** 1 chamada pelo iPhone e 1 pela web, para o log de descoberta mostrar o que o
  claude.ai manda. Roteiro no bloco do Passo 8b3.
- **Stack rodando** no MacBook: postgres e servidor em `127.0.0.1:8000` com login Google ligado,
  exposto pelo Funnel em `https://<maquina>.<tailnet>.ts.net`. `VAULT_PATH` aponta para a **cópia** do
  vault (`~/assistente-teste/vault`). Banco na migração `0003`. 168 testes passando.
- **Próximo:** o Leonardo cria o Projeto e segue para o Passo 9 (Tier D).
- **Última atualização:** 2026-10-17, Opus 5.5 (executor do Passo 8b3), MacBook Air.

## Avisos vivos

- **Desde 2026-10-17 (Passos 8b e 8b2): toda chamada de ferramenta fica registrada** (`servidor/assistente/registro.py`).
  - Só é leitura o que está em `LEITURAS_PECAS` (`servidor.py`) ou `LEITURAS_BANCO` (`banco.py`). Leitura: só log
    INFO (`assistente.registro: Chamada <ferramenta>: ok autor=<conta> {'caminho': ...}`).
  - Escritas do banco (`ESCRITAS_BANCO`): só log; `_gravar` já grava a auditoria (`criar`, `desfazer`).
  - **Todo o resto** (escrita das peças, nome novo, bloqueada, inexistente, caminho `<hash12>_<nome>`): linha
    `escrever` **antes** da chamada e `ok`, `erro`, `cancelado` ou `negado` depois. Se a `escrever` não grava
    (banco fora), a chamada é recusada ("Escrita recusada") e nada muda (falha fechado).
  - A linha do resultado guarda em `registro_id` o id da sua linha `escrever`. A `escrever` tem `registro_id` vazio.
  - `dados`: vault, só o caminho da nota; Paperless, só ids inteiros (`document_id`, `tag_ids`...). Nunca texto.
  - `autor` = conta conferida na lista (claim `identidade` gravado por `auth.py` no login): e-mail no Google,
    login no GitHub (minúsculo). Sem token: `anonimo` (só em memória). Linhas antigas do banco ficam com autor vazio.
  - Nome fora de `^[A-Za-z0-9_]{1,60}$` vira `<nome invalido>` no log e no banco.
  - Ferramenta nova numa peça: ponha em `LEITURAS_PECAS` ou `ESCRITAS_PECAS`; sem isso, a leitura nova conta como
    escrita (duas linhas a mais por chamada). Ferramenta nova no banco: ponha em `LEITURAS_BANCO` ou `ESCRITAS_BANCO`
    (o teste falha até isso).

- **Desde 2026-10-17 (Passo 8b3): toda chamada também vira linha em `chamadas`** (`registro.py`, migração `0003`).
  - Uma linha por chamada, no fim, inclusive leitura: `momento` (início), `ferramenta`, `resultado`
    (`ok`/`erro`/`negado`/`cancelado`), `autor`, `cliente` e `versao_cliente` (clientInfo), `sessao`
    (cabeçalho `mcp-session-id`), `user_agent` (200 caracteres), `modelo_declarado`, `duracao_ms`, `auditoria_id`.
  - Nunca argumento nem conteúdo. Do HTTP, só `mcp-session-id` e `User-Agent`.
  - Falha aberto: sem banco, a chamada segue e o log mostra `Falha ao gravar a chamada`. A escrita continua
    falhando fechado pela linha `escrever` da `auditoria`.
  - `auditoria_id`: peça = a linha `escrever`; banco = a linha `criar` ou `desfazer`; leitura = vazio.
  - `modelo_declarado`: parâmetro `modelo` das 4 escritas do banco ou `_meta._modelo` da requisição. Fora de
    `^[A-Za-z0-9 ._-]{1,60}$`, descartado. Ninguém confere: é o que o modelo diz.
  - GRANTs: `assistente_escrita=ar` (INSERT, SELECT), `assistente_leitura=r`. A 0003 tira o UPDATE que os
    privilégios padrão do `01-papeis.sh` dariam. Tabela nova: conceda explicitamente na migração.
  - O downgrade da 0003 não apaga a tabela; subir de novo reaproveita.
  - **Log de descoberta TEMPORÁRIO ligado** (`assistente.descoberta`, classe `DescobertaCliente`): a cada
    `initialize` e `tools/call`, clientInfo, protocolo, sessão, User-Agent e os NOMES dos cabeçalhos e das chaves do
    `_meta`. Para desligar: tirar `app.add_middleware(DescobertaCliente())` de `servidor.py` e a classe.

- **Vault de teste (Passo 7, 2026-10-17):** `VAULT_PATH` no `.env` aponta para a cópia
  `~/assistente-teste/vault` (sem `.git`). O servidor escreve nela. Nunca aponte para
  `~/Desktop/Projetos/Obsidian`. Para atualizar a cópia: o `rsync` do Passo 7 (apaga o que não existe no
  original, inclusive a nota de teste).

- **Decisões do Leonardo (2026-10-17):** o Claude Code só conecta no MCP na máquina dedicada (B11
  da Sprint 2; nada disso no Mac agora). Vault no i7 com Syncthing em todos os aparelhos e GitHub
  privado mantido por enquanto (B12).

- **URL do Funnel fora do repo (2026-10-17):** o repo é público; nos docs ela aparece como
  `https://<maquina>.<tailnet>.ts.net`. A real: `tailscale funnel status`, ou o vault
  (`10-projetos/assistente-pessoal/maquinas-do-assistente-pessoal.md`). Nunca grave a real aqui.

- **Desde 2026-10-17 (revisor):** o compose não repassa mais `AUTH_DESATIVADA` ao servidor, e o
  servidor recusa subir sem login se `PUBLIC_BASE_URL` não for local. O smoke sem login do Passo 2
  não roda mais no container; o teste sem login fica nos testes em memória. `JWT_SIGNING_KEY` com
  menos de 32 caracteres também não sobe.

- **A9 Feito (2026-10-17):** conector no claude.ai conectado pelo Leonardo; a ferramenta respondeu.
  `listar_categorias_gasto` devolvia só "teste" (gastos do smoke, todos desfeitos). Desde o Passo 5b
  ela ignora gastos desfeitos (decisão do Leonardo, 2026-10-17): hoje deve voltar lista vazia.

- **Desde 2026-10-17 (Passo 5b):**
  - Peças prontas usam lista de permitidas (`PERMITIDAS` em `servidor/assistente/servidor.py`).
    Versão nova de peça: regenere a fixture; o teste falha até cada nome novo entrar em
    `PERMITIDAS` ou `BLOQUEADAS`. Os prompts das peças continuam visíveis.
  - `/register` (10 por hora) e `/authorize` (30 por hora) têm limite por IP; acima disso, 429.
    Reiniciar o servidor zera a contagem. Não esgote o limite na URL pública.
  - **Desde o Passo 5c:** `/consent` usa o limite do `/authorize`; `/token` e `/auth/callback`
    têm 60 por hora por IP. Teto global somando todos os IPs: `/register` 100 por hora,
    `/authorize` e `/consent` 300 por hora cada. `/token` não tem teto global: o refresh do
    conector não trava por abuso de terceiros.
  - **Desde o Passo 5c:** conta fora da lista não recebe token. A troca do código falha com
    `invalid_grant` (HTTP 401) e o log mostra `Troca de código negada para '<conta>'`.
  - O IP real vem do `X-Forwarded-For` que o Tailscale põe. Só vale quando a conexão vem do
    loopback ou do gateway da rede do Docker (no Mac, `172.20.0.1`). O log mostra
    `assistente.limite: /register de <ip>`.
  - Cliente registrado que não troca código por token em 1 dia some do volume `oauth` (30 dias
    até o Passo 5c). Uma limpeza por hora, no máximo, apaga do disco o que expirou (na hora de
    `/register` ou `/authorize`).
  - A imagem não consulta mais o PyPI na subida (`FASTMCP_CHECK_FOR_UPDATES=off`).

- **Funnel ligado desde 2026-10-17:** `https://<maquina>.<tailnet>.ts.net` → `127.0.0.1:8000`.
  Com o servidor parado, `/mcp` pelo Funnel deu 502 (conferido). Desligar: `tailscale funnel --https=443 off`.
- **Trava de segurança:** `.env` com `AUTH_DESATIVADA=false` desde 2026-10-17. Sem credenciais
  de login, o servidor não sobe (`SystemExit` em `_auth`). Nunca volte para `true` com o Funnel ligado.

- **Decisão do Leonardo (2026-10-17):** o login principal é pelo **Google**
  (`AUTH_PROVEDOR=google`, `GOOGLE_EMAILS_PERMITIDOS`). O GitHub fica no código
  como alternativa, sem uso.
- **Login ligado desde 2026-10-17 (Passo 5):** o servidor sobe com `AUTH_PROVEDOR=google`.
  Antes de qualquer `up`, confira `POST /mcp` sem token = 401. Se der outra coisa, rode
  `docker compose stop servidor` na hora.
- **Volume `oauth` (Passo 5):** guarda clientes registrados e tokens do login, cifrados com a
  `JWT_SIGNING_KEY`. `docker compose down -v` apaga também este volume: o conector precisa
  reconectar. Trocar a `JWT_SIGNING_KEY` tem o mesmo efeito.

- **Decisão do Leonardo (2026-10-16):** Paperless e outras configs permanentes só na
  produção (i7); no MacBook, só o que for teste descartável.
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
  Correção: `chflags -R nohidden servidor/.venv`. O flag voltou no Passo 3
  (2026-10-16); rode a correção antes de todo `uv run pytest`.
- `.env` local é de teste (senhas geradas, login Google de teste, URL do Funnel do Mac).
  Não serve para produção.
- O smoke do Passo 2 (`fastmcp.Client` sem token) não roda mais: com login ligado, `/mcp` dá
  401. Não desligue o login para rodá-lo. A partir do Passo 6, o teste é pelo claude.ai.
- O banco já tem 4 gastos de smoke (ids 1 a 4, todos desfeitos) e 8 linhas de
  auditoria (contagem de 2026-10-16, depois do smoke do Passo 3). Apague o
  volume (`docker compose down -v`) só com aviso ao Leonardo.

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

### Passo 3 — Conferir as ferramentas bloqueadas (2026-10-16, Opus 5.5, executor)

- **Resultado:** os 6 nomes antigos de `BLOQUEADAS` existiam com o prefixo certo.
  Entraram mais 9 (apagar do Paperless, de reserva). Teste novo cobre o bloqueio.
  Sem commit: aguarda revisão do Leonardo.
- **Formato do nome (verificado no código e na prática):** FastMCP 4.1.0,
  `fastmcp/server/transforms/namespace.py`: `Namespace` usa `f"{prefix}_"` e o
  nome vira `<namespace>_<nome>`. Pelo proxy real, `delete_note` aparece como
  `vault_delete_note`. `app.disable(names=...)` esconde de `list_tools()` e a
  chamada direta responde `Unknown tool: 'vault_delete_note'` (a nota ficou).
- **Como listei (sem dado real):** dentro do container, `fastmcp.Client` por
  stdio. `mcpvault` com pasta temporária vazia. `paperless-mcp --stdio` com
  `PAPERLESS_URL=http://127.0.0.1:1` e token falso: lista sem conectar (só avisa
  que não alcançou o Paperless). Cruzei com o código instalado em
  `/opt/uv-tools/paperless-mcp/lib/python3.13/site-packages/paperless_mcp/`.
  Nada de Paperless subiu no Mac (decisão do Leonardo).
- **mcpvault 0.16.0 (18):** `read_note`, `write_note` (modo padrão `overwrite`
  troca a nota inteira), `patch_note`, `list_directory`, `delete_note`,
  `search_notes`, `move_note` (`overwrite`), `move_file` (qualquer arquivo,
  `overwrite`), `read_multiple_notes`, `update_frontmatter`, `get_notes_info`,
  `get_frontmatter`, `manage_tags`, `get_vault_stats`, `list_all_tags`,
  `wiki_link`, `get_note_outline`, `read_note_lines`. Sem `annotations`.
- **paperless-mcp 0.1.0 (54 no padrão; 64 com `PAPERLESS_MCP_ENABLE_DELETE=true`):**
  - Leitura (`read_only_hint`): `search_documents`, `get_document`,
    `get_document_content`, `get_document_metadata`, `get_document_notes`,
    `get_document_history`, `find_similar_documents`, `download_document`,
    `get_document_thumbnail`, `get_next_asn`, `search_everywhere`,
    `search_autocomplete`, `list_tags`, `list_correspondents`,
    `list_document_types`, `list_storage_paths`, `list_custom_fields`,
    `list_trash`, `list_active_tasks`, `list_tasks`, `get_task`,
    `get_paperless_info`, `get_statistics`, `get_system_status`,
    `list_saved_views`, `get_saved_view`, `run_saved_view`,
    `get_document_suggestions`, `get_document_ai_suggestions`, `list_share_links`.
  - Escrita sem destruir: `upload_document`, `add_document_note`, `create_tag`,
    `create_correspondent`, `create_document_type`, `create_storage_path`,
    `create_custom_field`, `restore_documents`, `acknowledge_tasks`,
    `create_share_link`.
  - Escrita destrutiva: `update_document`, `update_tag`, `update_correspondent`,
    `update_document_type`, `update_storage_path`, `update_custom_field`,
    `set_document_custom_field`, `remove_document_custom_field`,
    `bulk_edit_documents`, `bulk_reprocess_documents`, `bulk_merge_documents`,
    `bulk_rotate_documents`, `split_document`, `delete_document_pages`.
  - Só com `PAPERLESS_MCP_ENABLE_DELETE=true`: `delete_document`,
    `delete_document_note`, `delete_tag`, `delete_correspondent`,
    `delete_document_type`, `delete_storage_path`, `delete_custom_field`,
    `bulk_delete_objects`, `empty_trash`, `delete_share_link`.
- **Achados de segurança (verificados):**
  - O proxy stdio não herda o ambiente do servidor: o `mcp` passa só
    `get_default_environment()` (HOME, PATH...) mais o `env` explícito. Com
    `PAPERLESS_MCP_ENABLE_DELETE=true` no processo pai, a peça seguiu com 54.
  - O `mcpvault` limita à pasta: `../../etc/passwd` e `list_directory ..` dão
    `Path traversal not allowed`; `/etc/passwd` vira `etc/passwd` dentro do
    vault (não achou). Symlink para fora é recusado no código (`resolvePath`);
    não testei symlink na prática.
  - O `mcpvault` tem `--read-only`; não usei (seria mudar lógica).
- **Mudou:**
  - `servidor/assistente/servidor.py`: `BLOQUEADAS` de 6 para 15 nomes, cada um
    com motivo; comentário com o formato do prefixo e o teste.
  - `servidor/tests/test_bloqueadas.py` (novo, 5 testes).
  - `servidor/tests/fixtures/ferramentas_pecas.json` (novo): nomes reais e versão
    de cada peça. `servidor/tests/fixtures/gerar_ferramentas_pecas.py` (novo):
    regenera a fixture dentro do container (comando no docstring).
- **Verificado:**
  - `uv run pytest` = `22 passed` (17 antigos + 5 novos), Python 3.14.2 local.
  - Teste se prova capaz de falhar: com `vault.delete_note` = 2 falhas; sem
    `paperless_empty_trash` = 2 falhas; arquivo restaurado e conferido com `cmp`.
  - `docker compose up -d --build servidor`: ok; a imagem tem a lista nova.
  - Smoke do Passo 2: 5 etapas OK (gasto id 4 criado e desfeito).
  - `criar_app` real no container, com vault temporário e Paperless falso:
    75 ferramentas (9 banco + 49 Paperless + 17 vault); nenhuma bloqueada visível.
- **Não verificado:** o pytest não roda na imagem (`--no-dev`); o teste novo não
  usa binário, então basta o local. Symlink no vault. Paperless real (só no i7).
- **Ferramentas duvidosas (Pendente: decisão do Leonardo; nenhuma foi mexida):**

  | Ferramenta | Risco | Recomendação |
  |---|---|---|
  | `vault_move_file` | move qualquer arquivo (anexos); `overwrite=true` apaga o destino | bloquear: sem uso previsto |
  | `vault_move_note` | `overwrite=true` apaga a nota de destino | bloquear até o commit diário do vault (PLANO 2.3) |
  | `vault_write_note` | modo padrão `overwrite` troca a nota inteira | manter: o Passo 7 cria notas; só o git recupera (vault no git ainda não confirmado) |
  | `paperless_bulk_edit_documents` | troca correspondente/tipo/tags de muitos documentos, sem desfazer | bloquear |
  | `paperless_update_document` | sobrescreve título, texto OCR e tags de um documento | manter: um documento por vez, com histórico no Paperless |
  | `paperless_get_document_ai_suggestions` | se o Paperless usar LLM externo, o documento sai de casa | manter; rever na Fase 2 ao configurar o Paperless |
  | `paperless_delete_share_link` | apaga link (só com deletes ligados) | manter liberada: revogar link reduz exposição |
  | `paperless_upload_document` | cria documento | manter; rever no ⚑ 2.4 (envio de arquivos) |
  | `paperless_update_storage_path` | renomeia arquivos em disco de todos os documentos do caminho | manter: reversível voltando o modelo |

### Passo 4 — Tailscale Funnel e cliente OAuth do Google (2026-10-17, Leonardo, guiado pelo Opus 5.5 orquestrador)

- **Fez:** o servidor foi parado (`docker compose stop servidor`; porta 8000 fechada). O Leonardo
  instalou o Tailscale standalone, ligou MagicDNS e HTTPS e rodou `tailscale funnel --bg 8000`.
  URL: `https://<maquina>.<tailnet>.ts.net`. Ele criou no Google Cloud o projeto
  `assistente-pessoal`, a tela de consentimento (externo, em teste, o Gmail dele como usuário de
  teste) e o cliente Web "assistente teste mac", com origem `https://<maquina>.<tailnet>.ts.net` e
  redirecionamento `https://<maquina>.<tailnet>.ts.net/auth/callback`.
- **`.env`:** `PUBLIC_BASE_URL` = URL do Funnel, `AUTH_PROVEDOR=google`, `AUTH_DESATIVADA=false`,
  `GOOGLE_EMAILS_PERMITIDOS` = Gmail do Leonardo. O Leonardo colou `GOOGLE_CLIENT_ID` e
  `GOOGLE_CLIENT_SECRET` (conferido só o formato, sem ler os valores).
- **Verificado:** `/mcp` pelo Funnel = 502 com o servidor parado. `tailscale funnel status` mostra
  443 → `127.0.0.1:8000`.
- **Não verificado:** o login de ponta a ponta (Passo 5).

### Passo 5 — Login real pelo Google (2026-10-17, Opus 5.5, executor)

- **Resultado:** o servidor está de pé atrás do Funnel com login Google. Sem token e com token
  falso, `/mcp` responde 401. O registro de cliente só aceita o callback do claude.ai. Sem commit.
- **O que o FastMCP 4.1.0 faz (lido no código instalado, `site-packages/fastmcp/server/auth/`):**
  - `providers/google.py:135-148`: o `GoogleTokenVerifier` chama o `tokeninfo` do Google com o
    token; `:158-168` confere `aud` = nosso client id; `:181-190` exige os escopos.
  - `providers/google.py:221-226`: `claims["email"]` vem do tokeninfo (ou do userinfo);
    `claims["email_verified"]` vem do tokeninfo, que manda **texto** (`"true"`/`"false"`), ou do
    `verified_email` booleano do userinfo. O texto `"false"` passava na regra antiga (`is False`).
  - `oauth_proxy/proxy.py:2168-2350`: `load_access_token` confere o JWT do FastMCP, troca pelo
    token do Google guardado e chama o verificador acima. `auth.py:985-998`: o middleware chama
    `verify_token`, que chama `load_access_token`; é onde a lista de permitidos entra.
  - Redirect URIs: `redirect_validation.py:453-454` aceita **qualquer** URI (menos `javascript:`,
    `data:` etc.) quando `allowed_client_redirect_uris` é `None`, o padrão
    (`oauth_proxy/proxy.py:512-514`, `:1015-1024`). `proxy.py:959-981`: se o cliente mandar o client
    id do Google direto, sem DCR, o FastMCP cria um cliente na hora, que aceita redirect não
    registrado (`models.py:330-332`), só freado pela lista de padrões.
  - Armazenamento: `proxy.py:596-620` cria um `FileTreeStore` cifrado (Fernet, chave derivada da
    `JWT_SIGNING_KEY`) em `settings.home/oauth-proxy/<impressão da chave>`. `settings.py:72`:
    `home` = `user_data_dir("fastmcp")`; no container é `/home/assistente/.local/share/fastmcp`
    (conferido). Guarda clientes, tokens do Google, códigos e refresh. Sem volume, o rebuild apaga.
- **Decisões (técnicas, reversíveis):**
  1. `email_verified` falha fechado: só aceita `True` ou o texto `"true"` (sem diferenciar
     maiúsculas). Ausente, `None`, `False`, `"false"` ou vazio = recusa.
  2. Redirect URIs restritos por config (`AUTH_REDIRECTS_PERMITIDOS`). Vazio = os dois do
     claude.ai: `https://claude.ai/api/mcp/auth_callback` e `https://claude.com/api/mcp/auth_callback`.
     O claude.com entrou porque a documentação da Anthropic avisa que o callback pode mudar para ele
     (`support.claude.com/en/articles/11503834`; `claude.com/docs/connectors/building/authentication`).
     Vale para Google e GitHub. Claude Code (loopback) fica de fora de propósito.
  3. Volume nomeado `oauth` em `/home/assistente/.local/share/fastmcp`, com `FASTMCP_HOME` fixado
     no Dockerfile. Motivo: o rebuild não derruba o conector. O conteúdo é cifrado.
- **Mudou:**
  - `servidor/assistente/auth.py:55-60`: `GoogleRestrito._identidade` falha fechado.
  - `servidor/assistente/config.py:10-15`: `REDIRECTS_CLAUDE`; `:38-40`: campo
    `auth_redirects_permitidos`; `:62-67`: validador (vírgula; vazio = padrão).
  - `servidor/assistente/servidor.py:72-73`: `allowed_client_redirect_uris` nos dois provedores.
  - `servidor/Dockerfile`: `FASTMCP_HOME` e a pasta criada com dono `assistente`.
  - `docker-compose.yml`: `AUTH_REDIRECTS_PERMITIDOS` no serviço `servidor`; volume `oauth`.
  - `.env.example`: `AUTH_REDIRECTS_PERMITIDOS` comentado; aviso sobre trocar a `JWT_SIGNING_KEY`.
  - `servidor/tests/test_auth.py`: 11 casos de `email_verified`; teste do padrão de redirects;
    teste de `/register` (6 URIs × 2 provedores) com `fastmcp.settings.home` em pasta temporária.
  - `.env`: não mexi.
- **Verificado:**
  - `uv run pytest` = `41 passed` (22 antes). Sem as correções, 12 testes novos falham
    (conferido revertendo e restaurando); o caso `"false"` em texto falhava na regra antiga.
  - `docker compose up -d --build servidor`: build ok, `migracao` saiu com 0. Logs sem
    `SystemExit`, sem `AUTH DESATIVADA`, sem traceback.
  - Pelo Funnel (`https://<maquina>.<tailnet>.ts.net`):

    | Requisição | Código | Detalhe |
    |---|---|---|
    | `GET /.well-known/oauth-protected-resource/mcp` | 200 | `resource` = `https://<maquina>.<tailnet>.ts.net/mcp` |
    | `GET /.well-known/oauth-authorization-server` | 200 | `issuer`, `authorize`, `token`, `register` em https na URL do Funnel |
    | `POST /mcp` sem token | 401 | `WWW-Authenticate: Bearer ... resource_metadata=".../.well-known/oauth-protected-resource/mcp"` |
    | `POST /mcp` com `Bearer xyz` | 401 | `error="invalid_token"` |
    | `GET /mcp` sem token | 401 | — |
    | `POST /register` com `https://claude.ai/api/mcp/auth_callback` | 201 | cliente criado |
    | `POST /register` com `https://claude.com/api/mcp/auth_callback` | 201 | cliente criado |
    | `POST /register` com `https://evil.example/cb` | 400 | `invalid_redirect_uri` |

  - Dentro do container, `/authorize` com o client id do Google (sem DCR): redirect
    `https://evil.example/cb` = 400; redirect do claude.ai = 302 para `/consent` do servidor.
  - O volume `assistente-pessoal_oauth` existe; a pasta é do usuário `assistente` e já tem
    `oauth-proxy/`.
- **Não verificado:**
  - Login de ponta a ponta com o Google (é o A9). E-mail fora da lista só no teste de unidade:
    a tela de consentimento está "em teste" com só o Gmail do Leonardo, então outra conta para
    no Google antes de chegar aqui.
  - Se o claude.ai usa DCR ou CIMD hoje. Os dois caminhos passam pela mesma lista de redirects.
  - Os 2 clientes de teste do `/register` ficaram no volume (sem uso, sem token).
- **Achado:** na subida, o FastMCP consulta `https://pypi.org/pypi/fastmcp/json` (checagem de
  versão). Não vaza dado, mas é uma chamada para fora. Desliga com `FASTMCP_CHECK_FOR_UPDATES`
  (`settings.py:336`). Pendente: decisão do Leonardo.

#### Roteiro do A9 (o orquestrador guia o Leonardo)

1. Antes: `docker compose ps` mostra `servidor` de pé. `curl -s -o /dev/null -w "%{http_code}"
   -X POST https://<maquina>.<tailnet>.ts.net/mcp` = 401.
2. Num terminal: `docker compose logs -f servidor` (deixe aberto).
3. claude.ai (web, logado na conta do Leonardo) → Configurações → Conectores → Adicionar conector
   personalizado. Nome: `Assistente (teste Mac)`. URL: `https://<maquina>.<tailnet>.ts.net/mcp`.
   Campos avançados de OAuth: deixar vazios.
4. Clicar em Conectar. O que esperar, em ordem:
   - página do FastMCP pedindo consentimento para o cliente "Claude" → Aprovar;
   - tela do Google "Fazer login" → escolher o Gmail da lista; o Google avisa que o app não foi
     verificado (modo teste) → Continuar; aceitar ver o e-mail;
   - volta ao claude.ai com o conector "Conectado" e as 9 ferramentas do banco.
5. Teste rápido numa conversa: "liste as categorias de gasto" → chama `listar_categorias_gasto`.
6. Diagnóstico pelos logs:
   - `POST /register` 400 `invalid_redirect_uri`: o claude.ai usou outro callback. Copie a URI
     do log (sem token), ponha em `AUTH_REDIRECTS_PERMITIDOS` (com as duas do padrão) e suba de novo.
   - `GET /authorize` 400 `invalid_redirect_uri` ou `invalid_client`: mesmo caso, pelo caminho sem DCR.
   - Erro do Google `redirect_uri_mismatch`: o cliente do Google precisa ter exatamente
     `https://<maquina>.<tailnet>.ts.net/auth/callback`.
   - Erro do Google `access_denied` ou "app em teste": o Gmail não está como usuário de teste.
   - `Acesso negado para '<e-mail>'` no log e `POST /mcp` 401 depois do login: o e-mail não está
     em `GOOGLE_EMAILS_PERMITIDOS` ou veio sem `email_verified`. Confira só o nome da variável e
     peça ao Leonardo para conferir o valor.
   - `POST /token` 4xx: veja a linha anterior; código expirado ou PKCE. Tente de novo do zero
     (remover e adicionar o conector).
   - 502 pelo Funnel: o servidor caiu; `docker compose ps` e `docker compose logs servidor`.
7. Se der certo: marcar A9 em `docs/IMPLANTACAO.md` com a data e seguir para o Passo 6.

### Revisor independente dos Passos 3–5 (2026-10-17, Opus 5.5, sem o contexto da conversa)

- **Pedido do Leonardo:** rodar o revisor e, se tudo correr bem, fazer o commit.
- **Achados de gravidade alta:** nenhum. Conferiu identidade Google, token de outro cliente,
  consentimento, CIMD, despacho por hash, segredos em log e permissões do volume.
- **Corrigido pelo orquestrador (erro claro):**
  1. `AUTH_DESATIVADA` desligava o login no endpoint público. Saiu do `docker-compose.yml`, e
     `_auth` (`servidor/assistente/servidor.py`) dá `SystemExit` se a URL pública não for local.
  2. `JWT_SIGNING_KEY` curta subia. Agora exige 32+ caracteres.
  3. Testes gravavam no `fastmcp.settings.home` real. `servidor/tests/conftest.py` isola numa pasta
     temporária.
  - **Verificado:** 46 testes passando; imagem reconstruída; `/mcp` pelo Funnel = 401; metadata = 200;
    o container não recebe `AUTH_DESATIVADA`.
- **Revisor apontou, sem correção (decisão do Leonardo):**
  - `BLOQUEADAS` é lista de bloqueio: ferramenta nova numa versão nova da peça entra liberada.
    Sugestão: lista de permitidas (`app.enable(..., only=True)`) ou teste que exige revisar todo nome.
  - `/register` público sem limite de requisições, e os clientes ficam no volume `oauth` sem
    expirar: dá para encher o disco. Sugestão: limite por IP em `/register` e `/authorize`.
  - Testes que provam menos: proxy falso não é `FastMCPProxy`; falta teste de `/authorize` com o
    client id do Google e redirect estranho; falta teste com respostas reais simuladas do tokeninfo.
  - `AUTH_REDIRECTS_PERMITIDOS` substitui o padrão do claude.ai em vez de somar.
  - Conferir parâmetros de `vault_write_note`, `vault_patch_note` e `paperless_update_document`
    (podem apagar conteúdo).

### Passo 5b — Correções do revisor dos Passos 3–5 (2026-10-17, Opus 5.5, executor)

- **Resultado:** os 5 apontamentos do revisor e as 2 pendências do Passo 5 estão corrigidos e
  cobertos por teste. Sem commit: o orquestrador confere e faz o commit.
- **Mudou:**
  1. Lista de permitidas: `servidor/assistente/servidor.py:32` (`PERMITIDAS`, 64 nomes: 15 do vault,
     49 do Paperless), `:65` (`BLOQUEADAS` fica como segunda trava e registro do porquê), `:128`
     (`_montar_peca`: esconde toda ferramenta da peça e mostra só as de `PERMITIDAS`). As do banco
     continuam todas. Os prompts do Paperless (`triage_inbox`, `monthly_review`, `find_duplicates`)
     continuam visíveis. Teste: `servidor/tests/test_bloqueadas.py`, com o `create_proxy` de verdade
     sobre uma peça falsa que tem os nomes reais mais `apagar_tudo`.
  2. Limite por IP: `servidor/assistente/limite.py` (novo, middleware ASGI em memória, janela de
     1 hora, 429 com `Retry-After`, IPv6 contado por /64, teto de 10 mil IPs lembrados). Ligado em
     `servidor/assistente/auth.py:43` (`get_middleware` do provedor; vale para Google e GitHub).
     Config: `servidor/assistente/config.py:44-50`; compose e `.env.example` com
     `LIMITE_REGISTER_POR_HORA=10`, `LIMITE_AUTHORIZE_POR_HORA=30`, `PROXIES_CONFIAVEIS`,
     `CLIENTES_TTL_DIAS=30`. Teste: `servidor/tests/test_limite.py`.
     Prazo dos clientes: `auth.py:68` grava o cliente registrado com prazo de 30 dias; `auth.py:77`
     tira o prazo quando ele troca código por token; `auth.py:54` roda o `cull()` do `FileTreeStore`
     no máximo uma vez por hora.
  3. Testes novos em `servidor/tests/test_auth.py`: `/authorize` com o client id do provedor
     (`:175`: redirect estranho = 400; callback do claude.ai = 302 para `/consent`); verificador do
     Google com respostas simuladas do tokeninfo e do userinfo, passando pela lista (`:220`).
  4. `AUTH_REDIRECTS_PERMITIDOS` soma ao padrão do claude.ai (`config.py:74-83`). Padrão sem caminho
     (ou só `/` e `*`), sem esquema ou sem host não sobe. `.env.example` atualizado.
  5. Parâmetros conferidos (abaixo). Nada novo bloqueado.
  6. `listar_categorias_gasto` ignora gastos desfeitos: `servidor/assistente/banco.py:161`. Teste:
     `servidor/tests/test_banco.py:82`.
  7. `ENV FASTMCP_CHECK_FOR_UPDATES=off` em `servidor/Dockerfile:32`. Valores aceitos (lidos em
     `fastmcp/settings.py:336-348`): `stable` (padrão), `prerelease`, `off`;
     `utilities/version_check.py:140-143` sai sem chamar o PyPI com `off`.
  - `servidor/tests/fixtures/gerar_ferramentas_pecas.py`: docstring diz que nome novo vai para
    `PERMITIDAS` ou `BLOQUEADAS`.
- **IP real atrás do Funnel (fonte: código do Tailscale, `ipn/ipnlocal/serve.go`):**
  `addProxyForwardedHeaders` faz `Header.Set("X-Forwarded-For", <IP do cliente>)`; no Funnel, o IP
  vem de `Tailscale-Ingress-Src`. `Set` troca o valor que o cliente mandou. Funnel não manda
  `Tailscale-User-Login` (só tráfego da tailnet manda; `tailscale.com/kb/1312/serve`), mas manda
  `Tailscale-Funnel-Request: ?1`. No container, a conexão chega de `172.20.0.1` (gateway da rede
  do compose, conferido em `/proc/net/route`), não de `127.0.0.1`. Por isso o padrão de proxies
  confiáveis é loopback mais o gateway do container.
  - Verificado pela URL pública: com `X-Forwarded-For: 1.2.3.4` forjado, o log registrou o IP
    público real pelo Funnel e `100.74.104.24` (o IP do Mac na tailnet) pelo caminho da tailnet.
- **Item 5 — o que cada ferramenta pode apagar (schemas lidos no container, peças fixadas):**

  | Ferramenta | Pode apagar | Recomendação |
  |---|---|---|
  | `vault_write_note` | `mode` padrão `overwrite`: troca a nota inteira (e o frontmatter, se vier). `append`/`prepend` só somam | manter (o uso normal precisa); o vault no git é que recupera |
  | `vault_patch_note` | troca um trecho exato (`oldString` → `newString`); `newString` vazio apaga o trecho; `replaceAll=true` troca todas as ocorrências. Falha se houver mais de uma sem `replaceAll` | manter: edita menos que `write_note` com `overwrite`, que seria a alternativa |
  | `paperless_update_document` | sobrescreve `title`, `content` (texto do OCR inteiro), `created`, ASN; `tag_ids`/`tag_names` **trocam** a lista de tags inteira; `clear_fields` tira correspondente, tipo, caminho e ASN; trocar o caminho move o arquivo no disco. Arquivo original fica | manter por enquanto (Paperless só no i7); rever na Fase 2.1 se o histórico do Paperless guarda o `content` antigo; se não guardar, bloquear |
  | `vault_update_frontmatter` | `merge=false` troca o frontmatter inteiro | manter |
  | `vault_manage_tags` | `remove` tira tags da nota | manter |
- **Verificado:**
  - `uv run pytest -q` = `89 passed` (46 antes).
  - Prova de falha: com o código do commit anterior e os testes novos, 18 falharam (limite, prazo,
    permitidas, nome sem decisão, categorias, redirects). Com a lista de redirects desligada e a regra
    antiga de `email_verified`, 20 falharam em `test_auth.py`, entre eles 4 de `/authorize` e 3 do
    tokeninfo. Com o proxy confiável ignorado, `test_ip_de_origem` falhou. Código restaurado e
    conferido com `cmp`; 89 passando de novo.
  - `docker compose up -d --build servidor`: build ok; `migracao` saiu com 0; logs sem erro, sem
    traceback, sem `AUTH DESATIVADA`. No container: `FASTMCP_CHECK_FOR_UPDATES=off`, limites 10/30,
    prazo 30.
  - `criar_app` no container com as peças de verdade (vault em pasta temporária vazia, Paperless
    falso): 72 ferramentas (9 banco, 15 vault, 48 Paperless); nenhuma fora de `PERMITIDAS`; nenhuma
    bloqueada. Só `paperless_delete_share_link` não aparece (precisa dos deletes ligados).
  - Pela URL do Funnel:

    | Requisição | Código |
    |---|---|
    | `POST /mcp` sem token | 401 |
    | `GET /.well-known/oauth-protected-resource/mcp` | 200 |
    | `POST /register` com `https://evil.example/cb` (pelo relay público) | 400 |
    | `GET /authorize` com client id falso e `X-Forwarded-For` forjado (relay público e tailnet) | 400 e 400 |

- **Não verificado:**
  - O 429 pela URL pública (de propósito; fica nos testes em memória).
  - O prazo e a limpeza com o login de ponta a ponta. O cliente atual do Leonardo foi registrado
    antes do 5b, não tem prazo e não expira. Os 2 clientes de teste do Passo 5 também ficam.
  - Paperless real (só no i7).
- **Decidi sozinho:**
  - Limite e prazo ligados ao provedor de login (`get_middleware`), não ao `main`: vale em todo
    `http_app`, inclusive nos testes.
  - Pedido recusado (400) também conta no limite.
  - IPv6 contado por bloco /64.
  - Prompts das peças ficam fora da lista de permitidas (são texto, sem ação).
  - Log em INFO com o IP de cada `/register` e `/authorize`, para ver abuso.
- **Limitações:**
  - O `/register` é chamado pelos servidores do claude.ai: todo usuário do claude.ai sai do mesmo
    bloco de IPs. Quem tentar registrar nosso endereço no claude.ai gasta a cota de 10 por hora e
    pode travar uma reconexão do Leonardo por até 1 hora.
  - A limpeza só roda quando chega `/register` ou `/authorize`. Sem pedido, nada novo é gravado.
  - O prazo usa o `_client_store` interno do `OAuthProxy` (FastMCP 4.1.0). Se a versão mudar, os
    testes de `test_limite.py` acusam.

### Passo 5c — Correções do revisor do Passo 5b (2026-10-17, Opus 5.5, executor)

- **Resultado:** os 3 erros claros do revisor do 5b estão corrigidos e cobertos por teste, mais
  4 das 5 melhorias baratas. Sem commit: o orquestrador confere e faz o commit.
- **Mudou:**
  1. Lista de permitidos na troca do código: `servidor/assistente/auth.py:97`
     (`_conferir_conta_do_codigo`) e `:120` (chamada antes do `super()`). Lê o código em
     `self._code_store`, valida o `access_token` do provedor com `self._token_validator.verify_token`
     e aplica `_identidade` mais a lista. Conta fora da lista, token recusado pelo provedor ou erro
     do provedor: apaga o código e levanta `TokenError("invalid_grant", ...)`. O SDK não aceita
     `access_denied` no `/token` (`mcp/server/auth/provider.py:106`, `TokenErrorCode`). O FastMCP
     troca o 400 de `invalid_grant` por 401 (`fastmcp/server/auth/auth.py:69`, `TokenHandler`).
     Nenhum token é emitido, e o cliente mantém o prazo. Vale para Google e GitHub (mixin `_Restrito`).
     Teste: `servidor/tests/test_auth.py:269` (`test_troca_do_codigo_so_para_conta_permitida`), pelo
     `POST /token` de verdade com PKCE, nos dois provedores.
  2. Limites em `/consent`, `/token` e `/auth/callback`: `auth.py:51` (`_limites`). `/consent` usa o
     limite do `/authorize` (30); `/token` e o callback usam `LIMITE_TOKEN_POR_HORA` (60). Testes:
     `servidor/tests/test_limite.py:62` (429 em `GET` e `POST /consent`) e `:77` (`/token` e callback).
  3. Teto global por caminho: `servidor/assistente/limite.py:121` (`__call__`, fila global à parte do
     mapa por IP, sem despejo). Padrão: `/register` 100, `/authorize` e `/consent` 300 por hora.
     Config: `servidor/assistente/config.py:47-50`. Prazo padrão do cliente sem token: 1 dia
     (`config.py:56`; a variável continua `CLIENTES_TTL_DIAS`). Compose e `.env.example` com
     `LIMITE_TOKEN_POR_HORA`, `LIMITE_GLOBAL_REGISTER_POR_HORA`, `LIMITE_GLOBAL_AUTHORIZE_POR_HORA`
     e `CLIENTES_TTL_DIAS=1`. Testes: `test_limite.py:87` (5 blocos /64 do mesmo /48: 3 passam,
     depois 429) e `:102` (com o mapa por IP esquecendo IPs, o teto continua contando).
  - Melhorias feitas:
    - Redirect só com `https`, sem `?`, `#`, `[` ou `]`: `config.py:86-91`. O FastMCP compara o
      caminho com `fnmatch` e ignora a query. Teste: `test_auth.py:134`, 7 casos novos.
    - Log na subida com os proxies confiáveis (`auth.py:49`). Aviso de `X-Forwarded-For` vindo de
      fora dos proxies confiáveis, no máximo um a cada 10 minutos (`limite.py:72`, `_avisar`). Os
      avisos de 429 usam o mesmo freio. Testes: `test_limite.py:163` e `:177`.
    - `test_limite.py:33` agora faz um pedido recusado (400) e prova que ele gasta a cota.
- **Verificado:**
  - `uv run pytest -q` = `112 passed` (89 antes).
  - Prova de falha: com o pacote `assistente` do 5b e os testes novos, 24 falharam (troca do
    código, `/consent`, `/token`, callback, teto global, padrões, avisos, prazo de 1 dia, redirects).
    Só sem a chamada de `auth.py:120`, os 6 casos de conta recusada falharam: o `/token` deu 200
    com `access_token` para `intruso@gmail.com`. Código restaurado e conferido com `cmp`; 112 passando.
  - `docker compose up -d --build servidor`: build ok; `migracao` saiu; logs sem traceback, sem
    erro, sem `AUTH DESATIVADA`. O log de subida mostra os proxies `127.0.0.0/8, ::1/128, 172.20.0.1`.
    No container: limites 10/30/60, tetos 100/300, prazo 1 dia.
  - Pela URL do Funnel (nenhuma chamada a `/register`):

    | Requisição | Código |
    |---|---|
    | `POST /mcp` sem token | 401 |
    | `GET /.well-known/oauth-protected-resource/mcp` | 200 |

- **Não verificado:**
  - A troca do código com login real de uma conta fora da lista. O teste simula o verificador do
    provedor; não loguei com outra conta Google para não gastar o fluxo real.
  - O conector do Leonardo depois do rebuild. Ele não passa pela troca do código (só pelo refresh
    em `/token`, limite 60 por hora por IP); o Passo 6 confirma pelo iPhone.
  - Os testes rodam no Python 3.14 local; a imagem usa 3.12 e não tem os testes. O servidor subiu
    no 3.12 sem erro.
- **Decidi sozinho:**
  - Erro `invalid_grant`, não `access_denied`: o SDK só aceita os códigos de `TokenErrorCode`.
  - Erro do provedor na conferência (rede, 5xx) também recusa e apaga o código: falha fechado.
    O usuário refaz o login.
  - `/token` e `/auth/callback` sem teto global: só gravam com código ou login válidos, e um teto
    global deixaria qualquer um travar o refresh do conector.
  - `/consent` divide o limite com `/authorize` (mesmo valor, cotas separadas por caminho).
  - Mantive `CLIENTES_TTL_DIAS` em dias (padrão 1): compatível com compose e `.env.example`.
  - O aviso de 429 por IP passou a sair no máximo uma vez a cada 10 minutos por caminho.
- **Ficou de fora:**
  - **Pendente:** limpeza periódica (`cull`) numa tarefa do lifespan. Não fiz: o lifespan do FastMCP
    roda dentro do gerenciador de sessões (`fastmcp/server/http.py:741-763`), e uma tarefa em
    segundo plano ali pede mais cuidado do que vale agora. A limpeza continua no `/register` e no
    `/authorize`, que são os caminhos que gravam cliente e transação. Arquivo de CSRF do `/consent`
    expira em 15 minutos e some na próxima limpeza.
- **Limitações:**
  - O teto global troca disco por disponibilidade: quem fizer 100 `/register` numa hora, de qualquer
    IP, trava reconexões novas do Leonardo por até 1 hora. O conector já conectado continua (refresh
    em `/token` não tem teto global). Reiniciar o servidor zera a contagem.
  - A conferência na troca do código usa `_code_store` e `_token_validator`, internos do `OAuthProxy`
    (FastMCP 4.1.0). Se a versão mudar, `test_troca_do_codigo_so_para_conta_permitida` acusa.

### Passo 6 — Teste pelo iPhone (em andamento, 2026-10-17, guiado pelo Opus 5.5 orquestrador)

- **Feito:** o Leonardo registrou pelo app um gasto real (categoria `mercado`, origem `manual`). No banco:
  linha em `gastos` com `desfeito = f` e auditoria `criar` no mesmo instante. Isso também prova que o
  conector seguiu conectado depois dos rebuilds do 5b/5c.
- **Verificado no banco (2026-10-17):** gasto real (id 5) ativo; gasto de teste (id 6) criado e desfeito;
  ponto: 1 `entrada`. Auditoria tem `criar`, `criar`, `desfazer`, `criar`, na ordem. O Leonardo disse que
  consultas, categorias e horas responderam certo.
- **Feito:** o Leonardo tinha esquecido a saída; registrou às 09:52. Entrada 09:35 → saída 09:52 = 17 min, igual ao que o app respondeu. Passo 6 Feito.

### Passo 7 — Vault com uma cópia (2026-10-17, Sonnet 5.5, executor)

- **Feito:**
  - `rsync -a --delete --exclude .git` do vault real para `~/assistente-teste/vault`: 138 arquivos no
    original e 138 na cópia, 0 pastas `.git` na cópia (1,8 MB).
  - `.env`: só a linha `VAULT_PATH` mudou (`sed`), para o caminho absoluto da cópia. Não li outras linhas.
  - `docker compose up -d --build servidor`: build ok, `migracao` saiu, logs sem erro. Não há linha "Vault não
    configurado": o vault montou. No container (uid 1000): `/vault` com 12 itens na raiz e escrita ok.
- **Verificado:**
  - Script `vault_teste.py` (scratchpad do orquestrador) dentro do container, `criar_app()` com a config real:
    24 ferramentas = 9 do banco + 15 `vault_*`; nenhuma de `BLOQUEADAS` visível.
    - Banco (9): `consultar_atividades`, `consultar_auditoria`, `consultar_gastos`, `consultar_ponto`,
      `desfazer_registro`, `listar_categorias_gasto`, `registrar_atividade`, `registrar_gasto`, `registrar_ponto`.
    - Vault (15): `vault_get_frontmatter`, `vault_get_note_outline`, `vault_get_notes_info`,
      `vault_get_vault_stats`, `vault_list_all_tags`, `vault_list_directory`, `vault_manage_tags`,
      `vault_patch_note`, `vault_read_multiple_notes`, `vault_read_note`, `vault_read_note_lines`,
      `vault_search_notes`, `vault_update_frontmatter`, `vault_wiki_link`, `vault_write_note`.
  - `vault_search_notes` (query "whatsapp"): resposta de 1666 bytes. `vault_read_note` de
    `00-inbox/onde-parei.md`: 4635 bytes. `vault_write_note` de `00-inbox/teste-assistente.md`: sem erro.
    O arquivo existe na cópia (78 bytes) e **não** existe no vault real.
  - Pela URL do Funnel: `POST /mcp` sem token = 401 (local também 401).
  - `cd servidor && chflags -R nohidden .venv; uv run pytest -q`: 112 passed.
- **Não verificado:**
  - Teste pelo app (claude.ai): é do Leonardo. O app pode precisar reconectar o conector ou atualizar a
    lista de ferramentas para mostrar as 15 novas.
  - Chamadas dos itens "apagar" e "mover" pelo app: no servidor, só conferi que não estão na lista.
  - O aviso de segurança do `vault_write_note`: ele sobrescreve nota existente; a cópia protege o original.
- **Decidi sozinho:**
  - Chamei as três ferramentas dentro do container com `fastmcp.Client` em memória, não pela URL pública,
    porque a URL exige login Google.
  - Deixei a nota `00-inbox/teste-assistente.md` na cópia, para o Leonardo ler/apagar no teste.
- **Roteiro do teste do Leonardo pelo app:**
  1. Abra o conector; se faltarem ferramentas, desconecte e reconecte (ou atualize a lista).
  2. Na tela de permissões, confira as 15 ferramentas `vault_*` novas (24 no total).
  3. "Busque no vault notas sobre o agente whatsapp."
  4. "Leia a nota onde-parei."
  5. "Crie uma nota de teste no inbox." (confira em `~/assistente-teste/vault/00-inbox/`)
  6. "Apague essa nota." O Claude deve dizer que não pode.
  7. Avise o orquestrador do resultado; só então marque o A11 como confirmado pelo app.

- **Passo 7, teste pelo app (2026-10-17):** o Leonardo confirmou busca, leitura e criação de nota na cópia; o pedido de apagar foi recusado (ferramenta inexistente). Passo 7 Feito.

### Passo 8 — Ficha das instruções do Projeto (2026-10-17, Sonnet 5.5, executor)

- **Feito:**
  - `docs/regras-de-negocio.md` (novo): ficha 1 "Instruções do Projeto Assistente", status **proposta**, com o
    texto para colar no Projeto, exemplos, cenário de teste e 9 perguntas em "Decisão sua".
  - `CLAUDE.md`: nova seção "Regras de negócio" aponta para o arquivo.
  - `SPRINT.md`: status do Passo 8 atualizado.
- **O texto cita:** as 9 ferramentas do banco e as 15 `vault_*` pelo nome real. Do Paperless só o prefixo
  e dois exemplos, porque ele não está ligado (só no i7). O texto manda avisar "O Paperless não está ligado
  ainda" e parar, sem improvisar.
- **Não verificado:** o texto no app. O Projeto não foi criado (é depois do ok do Leonardo). Nenhum teste
  novo; não mexi no servidor. O teste de contrato (nomes citados existem no app) está como Pendente na ficha.
- **Decidi sozinho:** usei "o dono" no texto, sem nome, porque o repo é público. O Leonardo pode trocar ao colar.
- **Falta:** o Leonardo responder as perguntas da ficha 1, aprovar, criar o Projeto, e marcar PLANO 1.6.

### Passo 8b — Registro de toda chamada de ferramenta (2026-10-17, Opus 5.5, executor)

- **Resultado:** toda chamada de ferramenta passa por um middleware do FastMCP; escritas das peças e
  tentativas negadas viram linha em `auditoria`, leituras vão só para o log. Sem commit: o orquestrador confere
  e faz o commit.
- **O que o FastMCP 4.1.0 faz (lido no `.venv`):**
  - `fastmcp/server/server.py:1357` (`call_tool`) monta o `MiddlewareContext` e roda a cadeia do app em
    `:1427`; a busca da ferramenta fica dentro dela, e `:1464` levanta `NotFoundError("Unknown tool")`.
    Por isso o `on_call_tool` do app principal vê as montadas, as escondidas e as inexistentes.
  - `fastmcp/server/mixins/mcp_operations.py:249-262`: `NotFoundError`/`DisabledError` viram o resultado
    de erro "Unknown tool" só depois da cadeia.
  - `fastmcp/server/middleware/middleware.py:239` (`on_call_tool`).
  - O proxy das peças devolve erro como `ToolResult(is_error=True)`, sem exceção
    (`fastmcp/server/providers/proxy.py:458-465`). O middleware confere os dois casos.
  - Identidade: `fastmcp/server/dependencies.py:665` (`get_access_token`) lê o token do `request.scope["user"]`
    da requisição HTTP e, sem ela, do contexto do SDK. O token é o que `GoogleRestrito.load_access_token`
    devolve (`claims.email`); o do GitHub traz `claims.login`.
- **Mudou:**
  - `servidor/assistente/registro.py` (novo): `identidade()` (`:35`), `caminhos_do_vault()` (`:56`, só `path`,
    `paths`, `oldPath`, `newPath`, cortados em 300 caracteres e 20 caminhos), `RegistroChamadas.on_call_tool`
    (`:96`).
  - `servidor/assistente/servidor.py:34-67`: `PERMITIDAS` virou `LEITURAS_PECAS | ESCRITAS_PECAS` (mesmos 64
    nomes). `:175`: middleware ligado com as escritas das peças montadas.
  - `servidor/assistente/banco.py:34`: `_autor()` usa `identidade()`. Antes só lia `login`: com Google, o autor
    das escritas do banco ficava vazio. `:256`: descrição de `consultar_auditoria` cita vault, Paperless e negadas.
  - `servidor/assistente/modelos.py:68`: `registro_id` aceita vazio; comentários com os valores de `tabela` e `acao`.
  - `servidor/alembic/versions/0002_auditoria_sem_registro.py` (nova, à mão): `ALTER COLUMN registro_id DROP NOT
    NULL`. O downgrade põe `0` nas linhas vazias e volta o `NOT NULL`; nada é apagado.
  - `servidor/tests/test_registro.py` (novo, 16 testes).
- **Linhas em `auditoria`:**

  | Caso | `tabela` | `acao` | `dados` |
  |---|---|---|---|
  | Escrita no vault | `vault` | `escrever`, depois `ok` ou `erro` | `{"caminho": ...}` |
  | Escrita no Paperless | `paperless` | `escrever`, depois `ok` ou `erro` | `{}` |
  | Bloqueada ou escondida | `vault` ou `paperless` | `negado` | caminho, se for do vault |
  | Nome desconhecido | `ferramenta` | `negado` | `{}` |
  | Escrita do banco (como antes) | `gastos`, `ponto`, `atividades` | `criar`, `desfazer` | dados gravados |

- **GRANTs:** não mudaram. `ALTER COLUMN` mantém os privilégios. Conferido no banco real e num banco de rascunho:
  `assistente_leitura=r`, `assistente_escrita=ar` (INSERT e SELECT; o UPDATE saiu na 0001). O `01-papeis.sh` não muda.
- **Verificado:**
  - `cd servidor && chflags -R nohidden .venv; uv run pytest -q` = `128 passed` (112 antes).
  - Prova de falha: com `servidor.py`, `banco.py` e `modelos.py` do `HEAD` e sem a 0002, 14 dos 15 testes
    novos falharam (só o de `caminhos_do_vault` passou, porque o módulo novo ficou). Com a linha `escrever`
    gravada sem travar (falha aberto), `test_falha_ao_gravar_auditoria_recusa_a_escrita` falhou. Com o `_autor`
    antigo, os 2 casos de identidade falharam (o do Google pelo bug; o do GitHub porque o código antigo não usa
    `registro.get_access_token`, que o teste simula). Sem o middleware, o teste pelo HTTP falhou. Código restaurado
    e conferido com `cmp`; 128 passando.
  - `test_identidade_pelo_http_com_token_do_google`: `POST /mcp` com Bearer pelo `http_app` de verdade e
    `GoogleProvider.load_access_token` simulado; o autor gravado é o e-mail.
  - Migração no Postgres, num banco de rascunho (`teste_migra_8b`, criado e apagado por mim): `0001` → linha
    com `registro_id 5` → `0002` → INSERT com `registro_id NULL` pelo usuário de escrita deu certo, UPDATE deu
    `permission denied` → SELECT pelo de leitura deu certo → downgrade: linhas mantidas, a vazia virou `0`,
    `NOT NULL` de volta → `0002` de novo.
  - `docker compose up -d --build`: `migracao` rodou `0001 -> 0002` e saiu com 0. Servidor subiu sem erro e sem
    traceback. `\d auditoria` no banco real: `registro_id` sem `not null`; `alembic_version = 0002`; as 13 linhas
    antigas continuam.
  - No container (`registro_container.py`, scratchpad do executor), cliente em memória: leitura de
    `00-inbox/onde-parei.md` (só log); escrita de `00-inbox/teste-passo8b.md` na cópia; `vault_delete_note`
    recusado ("Unknown tool"). No banco: linhas 14 `escrever`, 15 `ok` e 16 `negado`, `tabela = vault`,
    `dados = {"caminho": "00-inbox/teste-passo8b.md"}`, `autor = anonimo` (cliente sem token). Nenhuma linha com
    o texto da nota. A nota existe na cópia (41 bytes) e não existe no vault real. `consultar_auditoria` mostra as
    3 linhas com as mesmas 7 chaves de antes.
  - `POST /mcp` sem token = 401, local e pela URL do Funnel.
- **Não verificado:**
  - Uma escrita pelo app (claude.ai) com o token real do Leonardo. O teste pelo HTTP simula o token; o caminho do
    token até o middleware é o mesmo. O próximo uso pelo app deve gravar `autor` com o e-mail.
  - Paperless real (só no i7). As escritas do Paperless foram testadas com peça falsa.
  - Os testes rodam no Python 3.14 local; a imagem usa 3.12. O servidor e o script do container rodaram no 3.12.
- **Decidi sozinho:**
  - Falha fechado na escrita das peças: a linha `escrever` grava antes da chamada; sem ela, a chamada volta
    "Escrita recusada" e a peça nem é chamada. Gravar só depois deixaria escrever sem rastro e devolver erro de
    algo que aconteceu. A linha do resultado (`ok`/`erro`) e a `negado` falham aberto, com log ERROR: a escrita já
    aconteceu (ou já foi barrada) e o rastro principal existe. Leitura não depende do banco.
  - Duas linhas por escrita (`escrever` e o resultado), porque a `auditoria` é só INSERT: não dá para completar a
    linha depois.
  - Menor schema: só `registro_id` passa a aceitar vazio. As colunas `autor` e `dados` já existiam; não criei
    coluna nova. O caminho vai em `dados`.
  - Downgrade põe `0` nas linhas vazias em vez de recusar ou apagar: nenhum registro real tem id 0.
  - `tabela = "ferramenta"` para nome desconhecido; nome cortado em 60 caracteres (tamanho da coluna).
  - Sem token, `autor = "anonimo"` (só em teste em memória ou login desligado). Com login, sem token o servidor
    responde 401 antes de chegar na ferramenta: quem está fora não consegue encher a tabela.
  - Do Paperless não grava argumento nenhum (nem id de documento): o pedido foi não gravar valores.
  - `vault_manage_tags` com `operation=list` conta como leitura.
  - `_autor()` do banco passou a gravar o e-mail do Google (antes ficava vazio). As linhas antigas não mudam.
  - Descrição de `consultar_auditoria` ganhou "vault, Paperless e tentativas negadas" (o Claude vê esse texto).
- **Limitações:**
  - Se o processo morrer entre a chamada e a linha do resultado, fica só a linha `escrever`. A cópia (ou o git,
    no i7) mostra se a nota mudou.
  - O log INFO tem o e-mail e o caminho da nota; fica no log do container.

### Passo 8b2 — Correções do revisor do Passo 8b (2026-10-17, Opus 5.5, executor)

- **Resultado:** os itens 1, 2, 3, 4 e 6 do revisor do Passo 8b estão corrigidos e cobertos por teste. Sem migração
  nova. Sem commit: o orquestrador confere e faz o commit.
- **Mudou:**
  - Item 1, identidade: `servidor/assistente/auth.py:140` devolve uma cópia do token com o claim `identidade` (a conta
    já conferida na lista, minúscula). `servidor/assistente/registro.py:41` (`identidade()`) lê só esse claim; sem
    ele, `None` e o autor sai `anonimo`. `banco.py:42` (`_autor()`) usa a mesma função; só mudou o comentário.
  - Item 2, cancelamento: `registro.py:164` pega `BaseException`; `CancelledError` e afins gravam `cancelado` e a
    exceção sobe de novo. `registro.py:135`: a gravação depois da chamada roda em `anyio.CancelScope(shield=True)`
    (anyio 4.15.1 no `.venv`).
  - Item 3, classificação: `registro.py:111` (`_e_escrita`) diz leitura só para `leituras` (`LEITURAS_PECAS |
    LEITURAS_BANCO`) e não grava `escrever` para `auditadas` (`ESCRITAS_BANCO`). Todo o resto é escrita.
    `banco.py:37-39`: as 9 ferramentas do banco em duas listas. `servidor.py:173`: o middleware recebe as listas.
  - Item 4, ligação: `registro.py:118` (`_inserir`) devolve o id; a linha do resultado grava esse id em
    `registro_id`. `registro.py:82` (`ids_do_paperless`): do Paperless, só `id`, `*_id` inteiros e `*_ids` (até 20
    ids inteiros). `modelos.py:62-74`: comentários de `ferramenta`, `registro_id`, `acao` e `dados`.
  - Item 6, nome cru: `registro.py:53` (`nome_seguro`) troca o nome fora de `^[A-Za-z0-9_]{1,60}$` por
    `<nome invalido>` antes de logar e gravar (`registro.py:142`).
  - `servidor/tests/test_bloqueadas.py:73`: o fixture cria a tabela `auditoria`; nome bloqueado agora grava
    `escrever` antes.
  - `servidor/tests/test_registro.py`: 9 testes atualizados, o do nome comprido trocado pelo do nome inválido e 12
    novos (cancelamento direto e pelo cliente, nome fora das listas, caminho por hash de verdade, listas do banco,
    escrita do banco sem linha a mais, ids do Paperless, claim no `load_access_token` do GitHub e do Google, token
    sem claim, leitura de peça não montada). O teste HTTP ganhou o caso GitHub com e-mail público.
- **Linhas em `auditoria` agora:**

  | Caso | `tabela` | `acao` | `registro_id` | `dados` |
  |---|---|---|---|---|
  | Escrita no vault | `vault` | `escrever`, depois `ok`, `erro` ou `cancelado` | vazio; o resultado aponta para a `escrever` | `{"caminho": ...}` |
  | Escrita no Paperless | `paperless` | idem | idem | só ids inteiros |
  | Bloqueada, escondida, inexistente | peça ou `ferramenta` | `escrever`, depois `negado` | idem | caminho ou ids |
  | Leitura conhecida de peça não montada | peça | `negado` | vazio | caminho ou ids |
  | Nome inválido | `ferramenta` | `escrever`, depois `negado` | idem | `{}`, ferramenta `<nome invalido>` |
  | Escrita do banco (como antes) | `gastos`, `ponto`, `atividades` | `criar`, `desfazer` | id do registro | dados gravados |

- **Verificado:**
  - `cd servidor && chflags -R nohidden .venv; uv run pytest -q` = `145 passed` (128 antes).
  - Prova de falha, revertendo um item por vez em `registro.py` (e depois em `auth.py`) e rodando a suíte toda:
    - identidade antiga (`email` antes de `login`): 3 falhas, entre elas o HTTP com GitHub (autor virou o e-mail);
    - `load_access_token` sem o claim: 4 falhas (os 2 do claim e os 2 HTTP);
    - `except Exception`: 2 falhas (os 2 de cancelamento); sem o `shield`: as mesmas 2 falhas;
    - classificação antiga (só `ESCRITAS_PECAS` é escrita): 15 falhas, entre elas nome novo e caminho por hash;
    - `registro_id` sempre vazio: 8 falhas; Paperless sem ids: 2 falhas; nome cru cortado em 60: 6 falhas.
    - Código restaurado e conferido com `cmp`; 145 passando.
  - Caminho por hash: o teste registra no app uma ferramenta visível a apps (`meta.fastmcp.tool_hash` e
    `ui.visibility = ["app", ...]`) e a chama como `0123456789ab_<nome>`. Ela roda e grava `escrever` e `ok`.
  - Cancelamento pelo cliente: a sessão fecha com a escrita parada no meio; o servidor cancela e grava `cancelado`
    ligado à `escrever`. Rodou 5 vezes seguidas sem falha.
  - `docker compose up -d --build servidor`: `migracao` saiu com 0 (continua na `0002`), servidor subiu sem erro nem
    traceback. `POST /mcp` sem token = 401, local e pela URL do Funnel. O volume `oauth` não foi tocado.
  - No container (`registro_container.py`, scratchpad do executor), cliente em memória sem token: escrita de
    `00-inbox/teste-passo8b2.md` na cópia, `vault_delete_note` e `vault_delete_note;rm -rf` recusados. Linhas novas:
    17 `escrever` e 18 `ok` (`registro_id` 17), 19 `escrever` e 20 `negado` (`registro_id` 19), 21 `escrever` e 22
    `negado` (`registro_id` 21) com `ferramenta = <nome invalido>`, `tabela = ferramenta`, `dados = {}`. Autor
    `anonimo` em todas. Nenhuma linha nem log com o texto da nota. A nota existe na cópia (42 bytes) e não no vault
    real.
- **Não verificado:**
  - Uma escrita pelo app (claude.ai) com o token real do Leonardo. Os testes HTTP simulam o token do provedor;
    `_Restrito.load_access_token` roda de verdade. O próximo uso pelo app deve gravar `autor` com o e-mail.
  - Cancelamento real vindo do claude.ai (`notifications/cancelled`). O teste cobre o cancelamento pelo escopo do
    anyio, que é o que o SDK do MCP usa.
  - Os testes rodam no Python 3.14 local; a imagem usa 3.12. O servidor e o script do container rodaram no 3.12.
- **Decidi sozinho:**
  - Nome bloqueado, escondido ou inexistente grava `escrever` e depois `negado`. Pular a `escrever` exigiria repetir a
    busca de ferramenta do FastMCP antes da chamada; se a repetição errasse, uma escrita passaria sem rastro.
  - Com o banco fora, chamada bloqueada ou nome desconhecido volta "Escrita recusada" em vez de "Unknown tool". As duas
    recusam; a peça não é chamada.
  - Leitura conhecida de peça não montada (ex.: Paperless no Mac) grava só `negado`, sem `escrever`.
  - `negado` depois de `escrever` também liga pelo `registro_id`.
  - O claim guarda a conta minúscula, a mesma forma comparada com a lista. No GitHub, o autor sai `leonardoricheto`.
  - `load_access_token` devolve cópia do token (`model_copy`): não muda o objeto que o provedor pode guardar em cache.
  - Token sem o claim `identidade` (não deveria existir com login ligado) vira `anonimo` no registro e autor vazio no
    banco, como antes sem token.
  - Ids do Paperless: chave `id`, `*_id` ou `*_ids`, valor inteiro (booleano não conta), até 20 por lista.
    `task_id` é texto na peça: fica de fora.
  - Linha `cancelado` também para `KeyboardInterrupt` e afins (tudo que não é `Exception`).
- **Pendências do revisor (não feitas, a pedido do orquestrador):**
  - Item 5: filtro por `tabela` e `acao` em `consultar_auditoria`. **Pendente.**
  - Item 7: o downgrade da `0002` faz `UPDATE` na `auditoria` (põe `0` nas linhas vazias). **Pendente.**
  - Item 8: o teste de classificação por prefixo (`test_leituras_e_escritas_das_pecas_nao_se_cruzam`) depende de o
    nome começar com `read`, `get`... **Pendente.**
  - Item 9: o log INFO tem o caminho da nota (e o e-mail). **Pendente.**
- **Limitações:**
  - Se o processo morrer (não cancelar) entre a chamada e a linha do resultado, fica só a linha `escrever`.
  - A mensagem de erro "Unknown tool" do FastMCP devolve ao cliente o nome cru; isso não vai para o nosso log nem para o banco.

### Passo 8b3 — Origem de cada chamada (2026-10-17, Opus 5.5, executor)

- **Resultado:** toda chamada de ferramenta, inclusive leitura, vira uma linha na tabela nova `chamadas`, com
  cliente MCP e versão, sessão, user-agent, resultado, duração e modelo declarado. Sem commit: o orquestrador
  confere, roda o revisor e faz o commit.
- **O que o FastMCP 4.1.0 e o SDK `mcp` 2.3.0 expõem (lido no `.venv`):**
  - clientInfo: `context.fastmcp_context.session.client_params.client_info` (`mcp/server/session.py:65`, que lê
    `mcp/server/connection.py:243`). Vale para os dois protocolos:
    - 2025-06-18 e anteriores: o `initialize` grava (`mcp/server/runner.py:239`);
    - 2026-07-28: não há `initialize`; o clientInfo vem no `_meta` de cada requisição
      (`io.modelcontextprotocol/clientInfo`, `mcp_types/_types.py:59`) e o SDK monta o mesmo `client_params`
      (`mcp/server/connection.py:262`, `from_envelope`). O cliente em memória do fastmcp usa este.
  - `on_initialize` do middleware: `fastmcp/server/low_level.py:192` e `:378`; a mensagem traz
    `params.client_info` e `params.protocol_version`.
  - `_meta` cru da requisição: `FastMCPRequestContext.meta` (`fastmcp/server/dependencies.py:82`), por
    `context.fastmcp_context.request_context` (`fastmcp/server/context.py:312`).
  - Sessão: `Context.session_id` (`fastmcp/server/context.py:707`) gera um uuid novo quando não há sessão
    (protocolo 2026-07-28, cliente em memória). Por isso o registro grava só o cabeçalho `mcp-session-id`.
  - Cabeçalhos: `get_http_request()` (`fastmcp/server/dependencies.py:579`); sem HTTP, `RuntimeError`.
    `get_http_headers()` (`:600`) tira `authorization` e `cookie`, mas o registro nem usa: lê só os 2 cabeçalhos.
  - Pedido sem token não chega ao middleware: o 401 sai antes. Quem está fora não enche a tabela.
- **Mudou:**
  - `servidor/assistente/registro.py`: `origem()` (`:131`), `modelo_declarado()` (`:92`), `anotar_auditoria()`
    (`:77`), `on_call_tool` (`:241`) grava a linha de `chamadas` no `finally`, blindado contra cancelamento
    (`:233`); a lógica antiga da auditoria foi para `_chamar` (`:265`), sem mudar de comportamento.
    `DescobertaCliente` (`:330`): log temporário.
  - `servidor/assistente/modelos.py:79`: modelo `Chamada`.
  - `servidor/alembic/versions/0003_chamadas.py` (nova, à mão): cria `chamadas` e o índice de `momento`;
    REVOKE ALL e GRANTs explícitos; downgrade sem efeito.
  - `servidor/assistente/banco.py`: parâmetro opcional `modelo` em `registrar_gasto`, `registrar_ponto`,
    `registrar_atividade` e `desfazer_registro` (`:35`; a ferramenta não usa, só o registro lê).
    `_gravar` e `desfazer_registro` avisam o id da auditoria depois do commit (`:116`, `:272`).
    `consultar_auditoria` com filtros `tabela` e `acao` (`:276`; item 5 do revisor do 8b). Ferramenta nova
    `consultar_chamadas(inicio, fim, ferramenta?, cliente?, limite<=200)` (`:296`). `LEITURAS_BANCO` com ela.
  - `servidor/assistente/servidor.py:174-177`: comentário e o middleware de descoberta.
  - `servidor/tests/test_chamadas.py` (novo, 23 testes); `servidor/tests/test_bloqueadas.py` (lista do banco).
  - `docs/regras-de-negocio.md`: ficha 1 ganhou "Mudança proposta (Passo 8b3)", status **proposta**.
- **Verificado:**
  - `cd servidor && chflags -R nohidden .venv; uv run pytest -q` = `168 passed` (145 antes).
  - Prova de falha, revertendo um item por vez e rodando a suíte toda:
    - sem gravar `chamadas`: 17 falhas; argumento no `user_agent`: 5; modelo sem validar: 7;
    - sem o `shield`: 1 (cancelado); sem o vínculo do banco: 2; descoberta logando valores: 2;
    - sem o filtro `tabela`: 1; GRANT com UPDATE: 1; sem o REVOKE: 1; downgrade com `drop_table`: 1.
    - Código restaurado e conferido com `cmp`; 168 passando. Cancelamento: 5 rodadas sem falha.
  - Banco de rascunho `teste_migra_8b3` (criado e apagado por mim), com os mesmos privilégios padrão do
    `01-papeis.sh`: `0002` → linha em `auditoria` → `0003` → `\dp chamadas` = `assistente_escrita=ar`,
    `assistente_leitura=r`; sequência `assistente_escrita=rU`. Como `assistente_escrita`: INSERT e SELECT ok;
    UPDATE e DELETE `permission denied`. Como `assistente_leitura`: SELECT ok; INSERT `permission denied`.
    Downgrade para `0002`: a linha de `chamadas` e a de `auditoria` continuam. `0003` de novo: reaproveita, mesmos GRANTs.
  - `docker compose up -d --build`: `migracao` rodou `0002 -> 0003` e saiu com 0. Servidor sem traceback.
    Banco real: `alembic_version = 0003`, `\d chamadas` com as 12 colunas, `\dp` igual ao rascunho. As 22 linhas
    de `auditoria` continuam.
  - No container (`chamadas_container.py`, scratchpad do executor), cliente em memória sem token, clientInfo
    `teste-8b3 0.0.1`: leitura de `00-inbox/onde-parei.md`; escrita de `00-inbox/teste-passo8b3.md` na cópia com
    `_meta._modelo = claude-opus-5-5`. Linhas: `chamadas` 1 (`vault_read_note`, ok, 285 ms, sem auditoria), 2
    (`vault_write_note`, ok, `modelo_declarado = claude-opus-5-5`, `auditoria_id = 23`) e 3 (`consultar_chamadas`);
    `auditoria` 23 `escrever` e 24 `ok`. Nenhuma linha com o texto da nota. A nota existe na cópia (27 bytes) e
    não no vault real. `sessao` e `user_agent` vazios: sem HTTP.
  - `POST /mcp` sem token = 401, local e pela URL do Funnel, depois de cada `up`. O volume `oauth` não foi tocado.
- **Não verificado:**
  - O que o claude.ai manda de verdade (clientInfo, protocolo, User-Agent, sessão). Precisa do login do Leonardo.
    O teste HTTP simula um `initialize` de 2025-06-18; se o claude.ai usar o protocolo 2026-07-28 sem sessão,
    `sessao` fica vazio e o clientInfo vem do `_meta` (coberto pelo cliente em memória).
  - Se o claude.ai manda `_meta._modelo`: quase certo que não. Sem as 3 linhas novas da ficha 1, `modelo_declarado`
    fica vazio nas chamadas do app.
  - Os testes rodam no Python 3.14 local; a imagem usa 3.12. O servidor e o script do container rodaram no 3.12.
- **Decidi sozinho:**
  - Tabela `chamadas` falha aberto, para leitura e escrita: a escrita já tem rastro que falha fechado
    (`escrever` na `auditoria`, ou a transação do `_gravar` no banco). Travar leitura por causa desta tabela tiraria
    o app do ar sem ganho de segurança.
  - Uma linha só, gravada no fim (a tabela é só INSERT): assim cabem resultado e duração. `momento` = início.
    Se o processo morrer no meio, a chamada fica sem linha em `chamadas` (a `escrever` da auditoria fica).
  - `sessao` só do cabeçalho `mcp-session-id`: o `session_id` do FastMCP inventa um uuid quando não há sessão.
  - `auditoria_id` sem chave estrangeira, como `registro_id`: o vínculo nunca derruba a linha.
  - Downgrade da 0003 sem efeito: apagar a tabela apagaria o histórico. A subida confere se a tabela existe.
  - Modelo declarado: parâmetro `modelo` só nas 4 escritas do banco; nas peças, só `_meta._modelo` (schema das
    peças intocado). Inválido é descartado, sem falhar. Não criei ferramenta "declarar modelo por sessão": a
    declaração ficaria velha se a sessão trocasse de modelo ou de conversa, e custaria uma chamada a mais.
  - O argumento `modelo` é lido de qualquer ferramenta que o receba (hoje só as 4 do banco têm o parâmetro).
  - Texto de fora (clientInfo, cabeçalhos) passa por limpeza: só caracteres imprimíveis, cortado no tamanho da coluna.
  - `consultar_auditoria`: `tabela` e `acao` com valores fixos (Literal); valor fora da lista é recusado.
  - `consultar_chamadas`: padrão de 50 linhas; ordem do mais novo; `momento` no fuso de Brasília. A linha da
    própria consulta só aparece na consulta seguinte.
  - O log de descoberta mostra também os nomes das chaves do `_meta` (nunca valores): mostra se o claude.ai manda
    algo como modelo ou conversa.
- **Roteiro de coleta (Leonardo, pendente):**
  1. No iPhone, no app do Claude, numa conversa com o conector "Assistente": peça "consulte meus gastos de hoje".
  2. Na web (claude.ai no navegador), outra conversa: peça "liste as categorias de gasto".
  3. Avise o orquestrador. Ele roda no Mac:
     `docker compose logs servidor --since 2h | grep -E "assistente.descoberta|Falha ao gravar a chamada"`
     e, no banco, `docker compose exec -T postgres psql -U assistente_dono -d assistente -c "select id, momento,
     ferramenta, resultado, autor, cliente, versao_cliente, sessao, user_agent, modelo_declarado, duracao_ms
     from chamadas order by id desc limit 10"`.
  4. O orquestrador confere: `cliente`, `versao_cliente` e `user_agent` preenchidos; `sessao` preenchido ou vazio
     (protocolo 2026-07-28); `autor` = o e-mail; os nomes de cabeçalho. Se o desenho bater, desliga o log de descoberta
     (tirar a linha de `servidor.py` e a classe) num passo curto.
- **Pendências do revisor do 8b (continuam):** item 7 (downgrade da 0002 faz UPDATE), item 8 (teste por prefixo) e
  item 9 (log INFO com caminho e e-mail). **Pendente.** O item 5 (filtros) foi feito aqui.
- **Limitações:**
  - `modelo_declarado` é o que o modelo diz; não há como conferir.
  - O log de descoberta tem User-Agent, sessão e clientInfo (sem segredo). Fica no log do container até ser desligado.

### Revisor do Passo 8b3 (2026-10-17, Opus 5.5) e correção do orquestrador

- **Erro claro:** nenhum. Sem vazamento de cabeçalho, token ou argumento; migração e GRANTs certos.
- **Corrigido (média):** registro de chamadas sem prazo prendia leituras com o Postgres travado.
  `servidor/assistente/db.py`: `connect_timeout=3`, `statement_timeout=5000` e `pool_timeout=3` no
  Postgres; teste em `servidor/tests/test_db.py`. Verificado no container: `statement_timeout` = 5s.
- **Corrigido (baixa):** docstring de `consultar_chamadas` diz que cliente, user_agent e modelo são dado.
- **Pendente:** paginação de `consultar_chamadas` (`antes_id`); teste de fuso no limite do dia;
  desligar o log `DescobertaCliente` depois da coleta do Leonardo; retenção da tabela `chamadas`.

## Prompt do próximo passo

> **Passo 9 — Usar alguns dias e anotar o que faltou (A12).** Tier D · do Leonardo · sem modelo.
> O Opus 5.5 só guia, se o Leonardo pedir.
>
> **Antes:** o Leonardo responde as perguntas da ficha 1 em `docs/regras-de-negocio.md`, aprova a ficha
> (muda o status para aprovada) e cola o texto no Projeto "Assistente" do claude.ai (PLANO 1.6).
>
> **Faça, por alguns dias:**
> 1. Use o app pelo Projeto: gastos, ponto, diário e notas do dia a dia.
> 2. Anote em `docs/IMPLANTACAO.md` (A12) o que faltou: ferramenta, categoria, resposta ruim, confirmação
>    longa demais, caso que o texto do Projeto não cobriu.
> 3. Se o Claude errar uma regra, diga a correção ao orquestrador: ela vira ficha ou regra na hora.
>
> **Pronto quando:** A12 tem a lista do que faltou e o Leonardo diz que pode fechar a Sprint 1 (Passo 10).
>
> **Passo 8b feito (2026-10-17, Opus 5.5):** registro de toda chamada de ferramenta; ver o bloco do Passo 8b.
> **Passo 8b2 feito (2026-10-17, Opus 5.5):** correções do revisor do 8b; ver o bloco do Passo 8b2. Itens 5, 7, 8
> e 9 do revisor ficaram pendentes (lista no bloco).
> **Passo 8b3 feito (2026-10-17, Opus 5.5):** tabela `chamadas` e log de descoberta temporário; ver o bloco do
> Passo 8b3. Antes do Passo 9: o Leonardo faz 1 chamada pelo iPhone e 1 pela web (roteiro no bloco), aprova ou
> não as 3 linhas novas da ficha 1, e o orquestrador confere o log e desliga a descoberta.
