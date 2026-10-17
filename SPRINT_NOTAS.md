# Sprint — notas de passagem (arquivo temporário)

> Lido no começo de toda sessão e escrito durante ela. O plano e a tabela de
> passos ficam em `SPRINT.md`. Sai do repo quando a sprint fechar.

## Onde estamos

- **Sprint 1 (Etapa A, teste no MacBook):** Passos 1 a 5 feitos. A9 Feito: o Leonardo conectou o
  conector no claude.ai. Revisor dos Passos 3–5 passou; erros claros corrigidos; commit feito
  (2026-10-17, sem push).
- **Stack rodando** no MacBook: postgres e servidor em `127.0.0.1:8000` com login Google ligado,
  exposto pelo Funnel em `https://<maquina>.<tailnet>.ts.net`. 46 testes passando.
- **Próximo:** Passo 6 (teste ponta a ponta pelo iPhone; Haiku 5.5, baixo). Antes, o Leonardo
  decide se `listar_categorias_gasto` ignora gastos desfeitos (ver avisos).
- **Última atualização:** 2026-10-17, Opus 5.5 (orquestrador), MacBook Air.

## Avisos vivos

- **Desde 2026-10-17 (revisor):** o compose não repassa mais `AUTH_DESATIVADA` ao servidor, e o
  servidor recusa subir sem login se `PUBLIC_BASE_URL` não for local. O smoke sem login do Passo 2
  não roda mais no container; o teste sem login fica nos testes em memória. `JWT_SIGNING_KEY` com
  menos de 32 caracteres também não sobe.

- **A9 Feito (2026-10-17):** conector no claude.ai conectado pelo Leonardo; a ferramenta respondeu.
  `listar_categorias_gasto` devolveu só "teste": vem dos gastos do smoke, todos desfeitos. Conferir
  no Passo 6 se a lista deve ignorar gastos desfeitos (regra de negócio: perguntar ao Leonardo).

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

## Prompt do próximo passo

> **Passo 6 — Teste ponta a ponta pelo iPhone.** Tier C · Haiku 5.5 · effort baixo · **supervisionado**.
> Só comece com o A9 feito (`[x]` em `docs/IMPLANTACAO.md`). Se não estiver, pare e avise.
>
> **Objetivo:** conferir que o Leonardo, pelo app do Claude no iPhone, registra e desfaz pelo
> conector, e que o banco e a auditoria batem.
>
> **Leia antes:** `SPRINT.md`, este arquivo (avisos vivos e Passo 5), `CLAUDE.md`,
> `docs/IMPLANTACAO.md` (A10).
>
> **Faça:**
> 1. Confira que o login está ligado: `docker compose ps` (servidor de pé) e
>    `curl -s -o /dev/null -w "%{http_code}" -X POST https://<maquina>.<tailnet>.ts.net/mcp` = 401.
>    Se não for 401, rode `docker compose stop servidor`, registre aqui e pare.
> 2. Anote a contagem atual: `docker compose exec postgres psql -U assistente_dono -d assistente
>    -c "select count(*) from gastos; select count(*) from ponto; select count(*) from auditoria;"`.
> 3. Peça ao Leonardo, pelo iPhone, nesta ordem: registrar um gasto de teste (ex.: R$ 1,00,
>    categoria `teste`); consultar os gastos de hoje; desfazer o gasto; registrar entrada e saída
>    de ponto; consultar as horas de hoje.
> 4. Confira no banco: o gasto novo com `desfeito = true`; as linhas de ponto; uma linha de
>    auditoria por escrita. Use só `select` com o usuário dono, sem mudar nada.
> 5. Veja `docker compose logs servidor`: sem `Acesso negado`, sem traceback.
> 6. Marque A10 em `docs/IMPLANTACAO.md`, status do Passo 6 no `SPRINT.md`, bloco do Passo 6 aqui,
>    "Onde estamos" atualizado. Escreva o prompt do Passo 7.
>
> **Não faça:**
> - Não leia, imprima nem grave valores do `.env`. Não mexa em `AUTH_DESATIVADA`.
> - Não apague linhas nem volumes. Não rode `docker compose down -v`.
> - Não faça commit sem o ok do Leonardo. Não faça push.
>
> **Pronto quando:** os 5 pedidos do item 3 funcionaram pelo iPhone e o banco bate.
