# Sprint — notas de passagem (arquivo temporário)

> Lido no começo de toda sessão e escrito durante ela. O plano e a tabela de
> passos ficam em `SPRINT.md`. Sai do repo quando a sprint fechar.

## Onde estamos

**Passagem de chat em 2026-10-17 (Opus 5.5 orquestrador, MacBook Air).** Leia esta seção, "Avisos
vivos" e "Prompt do próximo passo". O histórico de cada passo está em `SPRINT_HISTORICO.md`: abra só o
bloco do passo que precisar. **Esta seção é o único lugar do estado do projeto durante a sprint.**

- **Sprint 1 (Etapa A, teste no MacBook):** Passos 1 a 8e Feitos e commitados, sem push (revisor
  rodou em todos os de Tier A). 260 testes + 1 pulado (Postgres de rascunho). Falta só o uso real (Passo 9, que o
  Leonardo vai fazer no i7) e fechar a sprint (Passo 10). Fase 6b (fábrica de ferramentas) anotada no `PLANO.md`.
  Migração no banco: `0004`.
- **No ar no Mac:** postgres + servidor MCP em `127.0.0.1:8000`, login Google (só o e-mail do
  Leonardo), Funnel ligado (URL: `tailscale funnel status`), vault de **cópia** em
  `~/assistente-teste/vault`. Conector "Assistente (teste Mac)" conectado no claude.ai; testes
  pelo iPhone OK (gasto, desfazer, ponto, horas, vault, apagar recusado).
- **O que o servidor tem:** 11 ferramentas do banco (gastos, ponto, atividades, desfazer,
  auditoria, chamadas, `vincular_nota`) + 15 do vault (lista de permitidas). Toda chamada vai para a tabela
  `chamadas`; escritas de peça e tentativas negadas vão também para `auditoria`.
- **Ficha 1** (`docs/regras-de-negocio.md`, instruções do Projeto "Assistente"): **aprovada**
  inteira, inclusive as 3 linhas do 8b3 e as 4 mudanças do 8c (aprovadas e aplicadas em 2026-10-17). Fato com parte
  subjetiva conta como pedido de nota (decisão do Leonardo). **Colada no Projeto "Assistente" em 2026-10-17**; teste curto OK.
- **Coleta do clientInfo: encerrada** (Passo 8d). iPhone e web chegam idênticos (cliente
  `Anthropic/ClaudeAI`, versão `1.0.0`, protocolo `2026-07-28`, sem sessão, `user_agent=Claude-User`);
  não dá para diferenciar. Log `DescobertaCliente` desligado e removido.
- **Projeto "Assistente" criado no claude.ai (2026-10-17, Leonardo):** texto da ficha 1, conector ligado. Teste:
  gasto 7 (R$ 1,00, `teste`) criado e desfeito; auditoria 25 `criar` e 26 `desfazer`; chamadas 7 e 8 com
  `modelo_declarado=claude-haiku-5-5` (a conversa rodou no Haiku). 401 sem token conferido.
- **Próximo:** Passo 9 (usar alguns dias, Leonardo) e 10 (fechar a sprint). Sprint 2 (i7) só depois. Ficha 2 (retenção de `chamadas`)
  aprovada: guardar tudo (Leonardo, 2026-10-17).
- **Decisão do Leonardo (2026-10-17):** o i7 ainda não entra; tudo o que for do Mac pode ser feito (Passo 8e).
- **Decisão do Leonardo (2026-10-18), por conta de luz:** só o i7 fica ligado, com Debian 12 direto e cada serviço
  no seu Docker Compose, sem Proxmox (`docs/IMPLANTACAO.md` B2). O i5 desliga depois da Fase 1c do `PLANO.md`. Sem backup do
  banco por enquanto (B12 adiado); vault com Syncthing e GitHub. Consumo medido com a tomada medidora (PLANO 1.7).
  A implantação não aconteceu em 2026-10-18; o roteiro continua em `docs/IMPLANTACAO.md` § Roteiro da implantação.
- **Melhorias de 2026-10-18 (`PLANO.md` M1–M4):** M3 (lint diário do vault, só arquivos no repo) e M4 (este arquivo
  sem o histórico, agora em `SPRINT_HISTORICO.md`) feitos. M1 e M2 viraram a **Ficha 3, proposta**: falta o ok do
  Leonardo para trocar o texto da Ficha 1 no Projeto e o exemplo de `nota_vault` em `banco.py`. 260 testes + 1 pulado.
- **Última atualização:** 2026-10-17, Opus 5.5 (orquestrador, depois do revisor do 8e), MacBook Air.

## Avisos vivos

- **Desde 2026-10-18: `uv run pytest` no Mac não acha o pacote `assistente`.** O `.pth` editável do `.venv` está
  com a flag `hidden` do macOS, e o Python 3.14 ignora `.pth` oculto. Rode `PYTHONPATH=. uv run pytest`, ou tire a
  flag uma vez: `chflags nohidden .venv/lib/python3.14/site-packages/*.pth`. No i7 (Linux) não acontece.

- **Desde 2026-10-17 (Passo 8c): gasto, ponto e atividade têm `nota_vault`** (migração `0004`, só ADD COLUMN).
  - `registrar_*` aceitam `nota_vault`; `vincular_nota(tipo, id, caminho)` liga ou troca a nota, com linha
    `vincular` na `auditoria` (`dados`: `caminho` e, se havia, `anterior`). Devolve `vinculo` (id dessa linha) e
    `desfazer: {"tipo": "vinculo", "id": N}`; **sem campo `id`**, de propósito.
  - Desfazer o vínculo: `desfazer_registro(tipo="vinculo", id=N)`. Volta à nota anterior, grava `desfazer_vinculo`;
    o registro continua valendo. Só o vínculo em vigor mais novo do registro pode ser desfeito (pilha).
  - Caminho: só o formato é conferido (`caminho_da_nota` em `banco.py`, NFC gravado, NFKC conferido); o servidor
    não abre o vault.
  - O downgrade da 0004 é recusado se algum registro tem `nota_vault`, e em modo `--sql`.
  - Mensagens com o gênero do tipo: "o gasto", "a atividade" (`_o`, `_ao`, `_do`, `_desfeito` em `banco.py`).
  - `consultar_auditoria` devolve o `id` de cada linha desde o 8c.

- **Desde 2026-10-17 (Passos 8b e 8b2): toda chamada de ferramenta fica registrada** (`servidor/assistente/registro.py`).
  - Só é leitura o que está em `LEITURAS_PECAS` (`servidor.py`) ou `LEITURAS_BANCO` (`banco.py`). Leitura `ok`: só log
    **DEBUG** desde o 8d (`assistente.registro: Chamada <ferramenta>: ok autor=<conta> {'caminho': ...}`). Leitura com
    `erro` ou `cancelado`: **INFO** sem autor nem dados desde o 8e (`Chamada <ferramenta>: erro`). Escrita e negada
    continuam em INFO.
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
    (o teste falha até isso). Desde o 8e, ponha também em `CLASSIFICACAO_REVISADA` (`tests/test_registro.py`), decidindo
    à mão se lê ou escreve; o teste não olha o prefixo do nome.
  - Desde o 8e, `tests/test_contrato_ficha1.py` lê o texto do Projeto em `docs/regras-de-negocio.md`: ferramenta citada
    que não existe, bloqueada, ou ferramenta do banco/vault fora do texto faz o teste falhar. Ferramenta nova = proposta
    de linha na ficha 1.

- **Desde 2026-10-17 (Passo 8b3): toda chamada também vira linha em `chamadas`** (`registro.py`, migração `0003`). O log temporário `DescobertaCliente` foi removido no Passo 8d.
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

Os blocos de cada passo ficam em `SPRINT_HISTORICO.md` (desde 2026-10-18), que não se lê no começo da
sessão. Ao terminar um passo, acrescente o bloco no fim de lá e atualize "Onde estamos" aqui.

## Prompt do próximo passo

> Passo 8e (pendências do Mac) feito em 2026-10-17 pelo Opus 5.5; falta o revisor e o commit do orquestrador.
>
> Projeto "Assistente" criado e testado em 2026-10-17 (ver Onde estamos).
>
> **Passo 9 — Usar alguns dias** (Tier D, Leonardo). Usar pelo iPhone e pela web e anotar o que faltou em
> `docs/IMPLANTACAO.md` (A12). Roteiro mínimo:
> 1. Gasto com categoria existente; "sim" desfaz; gasto sem valor gera pergunta.
> 2. Ponto do dia e "quantas horas trabalhei hoje?".
> 3. Fato com as duas partes ("estudei Postgres 1 h e aprendi X"): atividade com `nota_vault` e nota nova em
>    `00-inbox` da **cópia**, com `registro: atividade-<id>`; o Claude diz onde criou a nota. Conferir no banco:
>    `select id, descricao, nota_vault from atividades order by id desc limit 3`.
> 4. "Liga a nota X ao gasto Y" e "sim": `vincular_nota` e `desfazer_registro` com tipo `vinculo`. O gasto **não**
>    fica desfeito; a auditoria tem `vincular` e `desfazer_vinculo`.
> 5. "Apague a nota X" é recusado; nota com instrução embutida é ignorada.
>
> **Restrições:** não leia valores do `.env`; vault só a cópia `~/assistente-teste/vault`; não desligue o login; não
> grave URL do Funnel, e-mail nem segredo no repo; commit só pelo orquestrador; nada é apagado.
