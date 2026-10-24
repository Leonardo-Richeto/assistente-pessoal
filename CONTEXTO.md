# Contexto do projeto (diário de passagem entre modelos)

Este arquivo é a memória do processo. Quem trabalhar no projeto (qualquer modelo, em qualquer
sessão) **lê este arquivo primeiro** e, ao terminar, **atualiza** as seções abaixo e escreve o
prompt para a próxima etapa. Ver "Regra de passagem" no fim.

Leitura complementar: `README.md` (arquitetura e princípios), `PLANO.md` (fases e tarefas),
`docs/IMPLANTACAO.md` (teste no MacBook → produção no i7), `AGENTS.md` (regras de código).

---

## Estado atual

- **Durante uma sprint, o estado vivo fica só em `SPRINT_NOTAS.md` § Onde estamos** (decisão de 2026-10-18,
  `PLANO.md` M4). Esta seção guarda o que vale entre sprints. Sprint 1 aberta (Etapa A, teste no MacBook).
- **Última atualização:** 2026-10-24, Opus 5.5 (Claude Code, MacBook Air): **implantação no i7 fechada** (menos o teste do ponto); próximo: Paperless único (Fase 2.1, prompt no fim). Entrada 2026-10-24.
- **Máquina (Leonardo, 2026-10-18):** só o i7 fica ligado, com Debian 13 direto (13 no lugar do 12 em 2026-10-23) e cada serviço no seu Docker
  Compose (sem Proxmox); o i5 desliga depois da Fase 1c do `PLANO.md`. Motivo: conta de luz.
- **Portabilidade (2026-10-19, Opus 5.5 no Kiro, PC Windows):** feita e ensaiada com dados sintéticos
  (`docs/MIGRACAO.md`, `PLANO.md` Fase 7). Backup diário cifrado volta a existir (substitui o "sem backup" de 10-18);
  no início ficaria desligado (Leonardo, 2026-10-21); ligado desde o início no HD de 500 GB do i7 (Leonardo, 2026-10-23).
- **PC Windows (2026-10-19, Leonardo):** é a máquina do trabalho (domínio corporativo). Uso: testar o sistema
  completo **sem dados reais**, só sintéticos, sem Tailscale/Funnel e sem credencial real. Produção continua no i7.

- **Fase 2b (vault inteligente, ideias do ai-memory) feita no Mac em 2026-10-21/22** (Opus 5.5 orquestrando
  subagentes); merge em `main` e push em 2026-10-22 (o GitHub liberou a chave Stripe falsa do teste dos hooks como "usada em testes"). Plano e registro passo a passo em `SPRINT_2B.md`. Implantada no i7 em
  2026-10-23. Mac = só desenvolvimento; i7 = hospedeiro (Leonardo, 2026-10-21).

## Histórico

### 2026-10-16 — Fase 0 (Opus 5.5, no app do Claude)

**Decisões tomadas nesta sessão**
- Arquitetura mudou para a "mescla": o app do Claude (iPhone/Mac/web) é a porta de entrada,
  conectado a um servidor MCP em casa como conector personalizado. Os dados (banco, vault,
  documentos) ficam em casa; o modelo é só o cérebro. Qualquer outro cliente MCP (ex.: ChatGPT)
  conecta igual.
- Exposição pela internet: **Tailscale Funnel** (grátis, sem domínio). Cloudflare Tunnel ficou
  como alternativa no compose (`--profile cloudflare`).
- Login: OAuth via **GitHub ou Google** (`AUTH_PROVEDOR`), com lista de permitidos.
- Não usar gateway MCP de terceiros: o próprio FastMCP junta tudo num endpoint só.
- Paperless: `paperless-mcp` (PyPI). O `paperless-ngx-mcp` (npm) foi testado e é incompatível
  com o SDK MCP do FastMCP 4 — descartado.
- Vault: `@bitbonsai/mcpvault` (npm).
- WhatsApp fica para depois (fase 6), com número/celular dedicado; API própria tipo WAHA,
  Telegram e Discord são a segunda etapa (fase 8).
- Teste primeiro no MacBook, produção depois no i7.

**O que mudou em relação ao plano anterior (modo antigo)**
- Antes: gateway próprio + Claude Code headless + WhatsApp/Telegram como entrada, só rede local.
  Agora: app do Claude como entrada, endpoint MCP exposto com login. O gateway volta na fase 6.
- Antes: vault acessado direto pelo Claude Code. Agora: via MCP pronto (mcpvault).
- O scaffolding antigo (feito na máquina do trabalho) **não** foi aproveitado; este repo começou do zero.

**O que foi construído**
- `servidor/assistente/banco.py`: ferramentas `registrar_gasto`, `consultar_gastos`,
  `listar_categorias_gasto`, `registrar_ponto`, `consultar_ponto` (horas com desconto de pausas),
  `registrar_atividade`, `consultar_atividades`, `desfazer_registro`, `consultar_auditoria`.
- Dois usuários de banco: leitura (só SELECT) e escrita (sem DELETE; auditoria só INSERT) —
  verificado em Postgres real.
- `servidor/assistente/auth.py`: login GitHub (por login) ou Google (por e-mail verificado).
- `servidor/assistente/servidor.py`: endpoint único; monta banco + proxies de Paperless e vault;
  `BLOQUEADAS` desliga ferramentas perigosas das peças prontas (link público, apagar nota etc.).
- Migração inicial Alembic (`0001`), `docker-compose.yml`, `.env.example`, README, PLANO, IMPLANTACAO.
- `NOME_USUARIO` e `PORTA_HOST` permitem uma segunda instância (esposa) na mesma máquina.

**Pendências / em aberto**
- Build Docker e o fluxo OAuth real com o claude.ai ainda não foram testados (Etapa A).
- Confirmar que o Tailscale Funnel funciona na versão do app instalada no Mac.
- Inventário completo de todas as máquinas (ver abaixo).
- E-mail: Gmail via conector nativo já; ferramenta própria multi-conta na fase 4b
  (Hotmail exige OAuth2; corporativo depende da política da corporação).
- Ligação pela operadora: ideia sem data.

### 2026-10-19 — Portabilidade do servidor (Opus 5.5, Kiro, PC Windows)

**Pedido:** "Plano de Portabilidade do Servidor" do Leonardo: migrar para outra máquina, inclusive em outra rede,
em ~30 min e sem perder dados; backup e migração pelo mesmo processo.

**O que foi feito**
- Repositório local: o `.git` errado na pasta pai (`Desktop\Projetos`, remote do vault, sem commits) foi
  removido; esta pasta agora é o clone do GitHub. Cópia da pasta antiga em `Desktop\Projetos\assistente-pessoal.bak-2026-10-19`.
- `docker-compose.yml`: `name: ${COMPOSE_PROJECT_NAME}`; bind mounts em `${ASSISTENTE_HOME}` (`data/postgres`,
  `data/sessoes/oauth`, `data/tailscale`, `vault`); `postgres:16.15` e `tailscale/tailscale:v1.104.1` com digest
  (multi-arch); healthchecks (Postgres por TCP; servidor saudável só com `/mcp` sem token = 401); Tailscale em
  container no perfil `tailscale`, `network_mode: service:servidor`, Funnel por `deploy/tailscale/funnel.json`.
  `cloudflared` removido (usava `latest`; a entrada única passa a ser o Tailscale).
- `.env.example`: `ASSISTENTE_HOME`, `COMPOSE_PROJECT_NAME`, `COMPOSE_PROFILES`, `TS_NOME`, `TS_AUTHKEY`,
  `AGE_DESTINATARIO`, `BACKUP_DESTINO`. **`VAULT_PATH` mudou de sentido:** agora é o caminho dentro do container
  (vazio ou `/vault`); a pasta é sempre `<home>/vault`. Os scripts recusam outro valor.
- `scripts/`: `lib.sh`, `preparar_host.sh` (substitui `deploy/preparar-maquina.sh`; Debian 12 ou 13; instala age e o
  timer do backup), `exportar.sh`, `importar.sh`, `verificar.sh`; testes em `scripts/testes/`. `deploy/backup-banco.sh`
  removido (o exportar o substitui; continua no git, commit `8d2ec8d`). `deploy/restaurar-banco.sh` mantido para os dados do Mac.
- `servidor/assistente/verificacao.py` (consulta de leitura pelas ferramentas MCP em memória, sem gravar nada, e
  HTTP local) + `tests/test_verificacao.py`. `_alembic` dos testes com `PYTHONIOENCODING=utf-8` (falhava no Windows).
- `deploy/systemd/assistente-backup.{service,timer}` (03:15); `deploy/ferramentas/Dockerfile` (age sem instalar no host).
- Caminhos do vault: `/srv/assistente/vault`, versões em `/srv/assistente/data/vault-versoes`, lint em
  `/srv/assistente/logs/vault-lint` (units, scripts, `SYNCTHING.md`, `IMPLANTACAO.md`).
- Docs: `docs/MIGRACAO.md` (novo), `README.md`, `docs/IMPLANTACAO.md` (B3–B8, B10–B12), `PLANO.md` Fase 7.

**Testes:** `uv run pytest` 267 passam, 1 pulado. `scripts/testes/test_retencao.sh` ok. `scripts/testes/ensaio_migracao.sh`
passou duas vezes no Windows (Docker Desktop, Git Bash, ~140 s): contagens, vault e `.env` iguais; `verificar.sh` ok.
Conferido também: backup diário religa o servidor; importar recusa `data/postgres` com dados e chave errada.
Bugs achados no ensaio e corrigidos: healthcheck do Postgres pelo socket dava "pronto" durante o initdb (a
migração falhava na primeira subida); `SHA256SUMS` listava o próprio temporário; `git` do Windows precisa de `C:/`.

**Decisões tomadas (sem perguntar, reversíveis)**
- Tailscale do container divide a rede do servidor: o Funnel chega por 127.0.0.1, já confiável para o
  `X-Forwarded-For`; sem IP fixo de rede Docker. O Tailscale do host fica só para SSH (dois nós).
- O importar só restaura `data/tailscale` com `--assumir-tailscale`; padrão = nó novo (evita duas máquinas com a
  mesma identidade).
- O "init.sql" do plano é o `deploy/postgres/01-papeis.sh` (precisa ler as senhas do `.env`, o que um `.sql` não faz).
- Retenção 7 diários + 4 semanais com a semântica do restic (o mais novo de cada dia e de cada semana ISO).

**Não testado / pendências**
- Tailscale em container e Funnel: só `docker compose config`; nunca subiu (máquina do trabalho, sem Tailscale).
- `preparar_host.sh` e o timer do systemd: só `bash -n`; rodar no i7 (`--dry-run` antes).
- Passagem ARM → x86 (Mac → i7) e o i7 em outra rede (4G): `PLANO.md` 7.4.
- Paperless fora do pacote (`PLANO.md` 7.3); os scripts param com erro se o serviço existir.
- Mac: depois do `git pull`, o compose novo não enxerga os volumes antigos (banco aparece vazio; o volume fica
  intacto). Para levar os dados do Mac, ver `docs/MIGRACAO.md` § Limites, **antes** de atualizar o código lá.
- O plano pede ensaio mensal numa VM do Proxmox do i5, mas o i5 vai ser desligado (decisão de 10-18): rever onde.
- Nada commitado (aguardando o Leonardo).

---

### 2026-10-21/22 — Fase 2b, vault inteligente (Opus 5.5 orquestrador, Claude Code, MacBook Air)

**Pedido:** implementar sozinho, do início ao fim, as melhorias da Fase 2b do `PLANO.md` (estudo do ai-memory do
Fabio Akita), com liberdade para acrescentar o que valesse. Leonardo aprovou tudo o que foi proposto (Ficha 5 e 6
decisões em `SPRINT_2B.md`).

**O que foi feito** (detalhe por passo em `SPRINT_2B.md`)
- Busca `buscar_vault` (FTS5 em memória, sem acento, pesos 10/8/5/4/1) e medida com 25 perguntas no vault real:
  24/25 entre as 5, MRR 0.847, ~3 ms. As perguntas ficam no vault (`90-meta/perguntas-da-busca.md`), não no repo público.
- `ler_nota` (versão + links e backlinks), `notas_recentes`, `contexto_inicial`, `escrever_nota` (troca só com a versão
  lida), `historico_nota` e `restaurar_nota` (commit por escrita, foto da edição do dono antes de trocar),
  `marcar_desatualizada`/`consultar_desatualizadas` (migração 0005), barreira de segredo em toda escrita, gitleaks no
  commit diário (stage e commits por escrita, push só depois da varredura limpa).
- Sessões do Claude Code: hooks `SessionStart`/`SessionEnd` (`ferramentas/sessoes/`), fila local, envio por SSH com
  chave restrita, tabela `sessoes` (migração 0006, só INSERT), `consultar_sessoes` no app (extensão da Ficha 5).
  Hooks instalados no Mac em 2026-10-22.
- Extra inspirado no `doctor` do ai-memory: `verificacao.py` confere migração, tabelas novas e o vault.

**Revisão:** revisor independente em cada passo Tier A e um final na branch; todos os achados claros corrigidos
(entre eles: perda de dado em nota grande/fora de UTF-8, edição do dono sumindo do git no restaurar, `index.lock`
órfão, config do git que executava comando, chave SSH que valia root no i7, gitleaks desligável por link, regex com
backtracking, falsos positivos em português).

**Verificado no Mac:** suíte do servidor e de `ferramentas/sessoes`, testes de shell, gitleaks real, testes de
Postgres num banco de rascunho, `docker build` arm64, ensaio de migração com a imagem nova (schema 0006, verificação ok).

**Não verificado:** i7 (amd64, systemd, uid 1000, SSH real, gitleaks lá), mcpvault real com as travas novas, Windows.

**Decisões do orquestrador (reversíveis):** comando Bash na fila só com a primeira linha (vale o "nunca conteúdo");
aviso do SessionStart por `systemMessage` + contexto marcado como dado; push do vault só por SSH; arquivo de
perguntas fora da busca real; `consultar_sessoes` sem `comandos`.

---

### 2026-10-23 — Implantação no i7 (Opus 5.5, Claude Code no MacBook Air, Leonardo no i7)

- **Máquina:** HP EliteDesk 800 G2 (placa 8054, BIOS 2.60), Windows apagado, **Debian 13**, hostname `i7`, IP
  192.168.15.200 reservado no roteador, usuário `leonardo` (uid 1000). BIOS para economia (`docs/IMPLANTACAO.md` B2a);
  `economia.service` (powersave + powertop). Sempre ligado (24/7, PLANO 1.8 adiado).
- **Discos:** SSD SanDisk 256 GB usável (realocado 1, incorrigível 2: vigiar). HD Seagate 500 GB do i5 (o avulso estava
  ruim) com SMART 184 em FAILING_NOW (25, parado), teste longo sem erro: **backup provisório** em `/srv/backup-hd`
  (`nofail`, `chattr +i` no ponto de montagem, para em 10 min). Sem compra de disco agora (Leonardo).
- **Stack:** `preparar_host.sh`, Tailscale do host (nó `i7`, só SSH) e do container (nó `assistente`, Funnel em
  `https://assistente.<tailnet>.ts.net`), `.env` com senhas `openssl rand -hex 32`, migração 0006, `verificar.sh` ok.
  Banco começou limpo (B10: o Mac só tinha teste).
- **Backup** ligado desde o início: chave do age gerada no Mac pelo Docker, identidade só em `~/identidade-assistente.txt`
  no Mac (corrigido em 2026-10-24); primeiro pacote no HD (1 MB). Ensaio de restauração: feito em 2026-10-24.
- **Vault:** clone do GitHub em `/srv/assistente/vault` (deploy key com escrita), Syncthing i7 ↔ Mac (pasta `vault`),
  `.git` do Mac movido para `~/vault-git-mac-parado` (D15). Timers 03:30/03:35/03:40; commit + gitleaks + push testados.
  `VAULT_PATH=/vault` (116 notas indexadas).
- **Correção:** `deploy/vault/commit-diario.sh` recusava o `git add` quando o `.gitignore` já ignorava `.stfolder`
  (pathspec `:!` de caminho ignorado). Passou para `core.excludesFile`, com teste (commit `0e03f9e`).
- **Sessões:** usuário `sessoes` com chave restrita (`command=`); a chave `~/.ssh/assistente_sessoes` do Mac enviou 2 sessões.
- **Funnel:** o DNS público só apareceu ~20 min depois de reiniciar o container do Tailscale. O claude.ai recusava a URL
  antes disso. O `verificar.sh` não percebe isso (PLANO 1.9).
- **Não verificado:** B8 e B9 (conector novo, Ficha 1 colada, testes pelo iPhone); ensaio de restauração; o HD parar de
  girar (`hdparm -C`); Pkg C-state no `powertop`; o backup noturno e o DNS do Funnel (PLANO 1.10); iPhone no Syncthing.

### 2026-10-24 — B8 e B9 (Opus 5.5, Claude Code no MacBook Air, Leonardo no app)

- **Projeto do claude.ai mudou:** o Projeto "Assistente" de 2026-10-17 não existia mais. Projeto novo agora abre em
  `claude.ai/code/project/...` e roda no **Claude Code na nuvem**: na tabela `chamadas` chega como cliente
  `claude-code` (2.1.310) e modelo Opus 5.5. O chat comum (sem Projeto) chega como `Anthropic/ClaudeAI` e **não** tem a
  Ficha 1. O conector aparece no "+" do chat comum; no Projeto, o Leonardo escolhe "Projeto → Assistente" em
  `claude.ai/new`. Texto da Ficha 1 colado no Projeto novo (B8).
- **B9 passou:** `contexto_inicial`, gasto → desfazer (com checagem de duplicata), gasto sem valor pergunta, busca
  (carro: o vault não tem decisão, "não achei" é certo), reescrever, segredo (`{{segredo:...}}`, `grep` limpo),
  restaurar, desatualizada → desfazer, resumo da conversa no diário (Ficha 4, com `registro: atividade-1`).
- **B9 falhou:** "o que eu fiz no Claude Code esta semana?" foi respondido pelo histórico do próprio ambiente, sem
  `consultar_sessoes`. Correção na Ficha 1 aprovada (Leonardo, 2026-10-24; `docs/regras-de-negocio.md`, "Mudança do
  B9"); texto novo colado e pergunta repetida às 07:06: `consultar_sessoes` chamada (chamada 59), resposta certa.
- **Sessões:** a sessão de 2026-10-23 estava na fila do Mac; enviada à mão. Envio automático ligado no Mac (launchd,
  a cada hora). O launchd não lê o Desktop (TCC): roda uma cópia de `enviar.py` e `fila.py` em
  `~/.local/share/assistente/sessoes/` (recopiar quando mudarem; `ferramentas/sessoes/README.md`).
- **Noite de 2026-10-24 conferida (journal do i7):** backup às 03:18 (1,1 MB, schema 0006, servidor e Tailscale
  religados), vault-commit às 03:30 (1 arquivo, gitleaks limpo, push feito), marcas 0, lint 0 erro e 20 avisos. O
  Funnel respondeu ao claude.ai às 06:34 (PLANO 1.10 feito). O usuário `leonardo` não está em `adm`/`systemd-journal`.
- **Ensaio de restauração ok (2026-10-24, Mac):** `scripts/ensaiar_restauracao.sh` (novo) com o pacote das 03:18:
  SHA256SUMS confere, banco restaurado com as 8 tabelas iguais ao `contagens.tsv`, vault com 128 notas e git íntegro.
- **Correção:** a identidade do age **não** está no gerenciador de senhas. A única cópia é `~/identidade-assistente.txt`
  no Mac (2026-10-23 16:09, permissão 600). O `.env` do Mac tem só a chave pública. Se o Mac se perder, os backups
  não abrem: guardar a identidade em outro lugar é pendência (decisão do Leonardo).
- **PLANO 1.9 no código:** o `verificar.sh` resolve o nome do Funnel num DNS público (DoH em 1.1.1.1 e 8.8.8.8, pelo
  IP) e chama o `/mcp` no IP público com `curl --resolve`; falha se o nome não existir. Motivo: o MagicDNS do host
  resolve o nome para a tailnet e o teste antigo passava com o DNS público vazio. O nome do Funnel vai para o
  Cloudflare/Google na consulta (ele já é público: DNS e certificado). No i7 (2026-10-24): `verificar.sh` tudo ok,
  com o Funnel pela internet = 401.
- **Inventário B1 do i7** (`deploy/inventario.sh`, powertop de 30 s): 16 GB em 4 × 4 GB DDR4-2133, sem slot livre.
  SMART igual ao de 2026-10-23 (HD: 184 = 25 FAILING_NOW, CRC 13155 parado; teste longo sem erro). Package em
  pc7/pc8 ~86% do tempo ocioso. Falta o microcódigo da CPU (`intel-microcode`). Resumo em `docs/inventario.md`;
  detalhe na nota `maquinas-do-assistente-pessoal` do vault. O i5 continua pendente (PLANO 1c.1).
- **Queda depois do reboot (12:00–12:23):** o `intel-microcode` já estava instalado; o reboot derrubou o login do
  claude.ai ("sign-in server temporarily unavailable"). Causa: o `/etc/resolv.conf` do i7 é do Tailscale do host
  (`100.100.100.100`); no boot o Docker subiu antes dele e o container ficou com "NO EXTERNAL NAMESERVERS DEFINED".
  Sem DNS, o servidor não baixa o cadastro do cliente do claude.ai (CIMD) e o `/token` responde 401. O
  `restart servidor` consertou o DNS, mas derrubou o Funnel: o Tailscale usa a rede do servidor e ficou na rede
  velha; `up -d --force-recreate tailscale` religou. Correção de vez: `dns: [1.1.1.1, 8.8.8.8]` no `servidor`
  e o `verificar.sh` resolve `claude.ai` e `oauth2.googleapis.com` de dentro do container (`checar_dns`).
  Regra nova em `docs/IMPLANTACAO.md` B7: nunca reiniciar só o `servidor`. Aplicado no i7 às ~12:28; Funnel pela
  internet = 401 e o conector do claude.ai respondendo às 12:29.
- **Microcódigo:** o kernel carrega a revisão `0xf0`, a última da Intel para o i7-6700, e ainda diz "GDS: Vulnerable:
  No microcode": a Intel não corrigiu o GDS para esse processador. Fica assim (só containers próprios no i7). A
  alternativa, `gather_data_sampling=force` no kernel, desliga o AVX; rever só na Fase 1c, com serviços de terceiros.
- **Lint isolado (2b-7):** em vez de usuário novo, o `vault-lint.service` roda numa caixa do systemd (sem rede, sem
  socket nenhum, sem o socket do docker, sem sudo, disco só leitura, grava só o `LINT_DIR`). Motivo: o código do lint
  vem do vault pelo Syncthing e o `leonardo` está no grupo `docker`; um usuário novo exigiria mudar as permissões do
  vault. Passos e prova no i7: `docs/IMPLANTACAO.md` 2b-7. **Não verificado** até rodar no i7.
- **Decisões (2026-10-24):** Paperless único para o Leonardo e a esposa (PLANO 2.1 e 1b.1); rever o mover nota em
  2026-11-07; Vaultwarden depois do Paperless; iPhone no Syncthing fica para depois; commit só no fim do trabalho
  (`AGENTS.md`).
- **Mac:** o `pytest` parou de achar o pacote `assistente` porque o macOS pôs a flag `hidden` no `.pth` do
  `.venv` e o Python 3.14 ignora `.pth` oculto. Correção: `chflags nohidden servidor/.venv/lib/python3.14/site-packages/*.pth`.
- **Registros reais:** atividade 1 (2026-10-23, dia de implantação no i7) e a nota `50-diario/2026/2026-10-24.md`.
- **Nota que mudou no meio (12:37):** pedido de troca depois de mudar a nota no Obsidian; o Claude releu (`ler_nota`),
  disse que a nota tinha mudado e perguntou antes de gravar; nenhum `escrever_nota`. A barreira do servidor (`versao`
  do `escrever_nota`) não chegou a ser acionada pelo app; ela tem teste próprio. Syncthing Mac → i7 em ~10 s.
- **Lint do vault no i7:** a rodada da noite de 2026-10-24 deu 0 erros e 20 avisos.
- **Não verificado:** teste do ponto (o Leonardo vai ajustar antes);
  o launchd enviando de fato (só rodou com a fila vazia); B9b (desligar o Funnel e a stack do Mac).

## O que já se sabe (dito pelo Leonardo, ainda não conferido nas máquinas)

**Máquinas**
- **i7-6700**, 16 GB DDR4, SSD SATA 240 GB + HD 500 GB (veio do i5 em 2026-10-23, só para o backup), sem GPU,
  hoje com Windows → produção, Debian 13 direto (decisão de 2026-10-18; versão trocada em 2026-10-23): o
  assistente e, depois, os serviços que vêm do i5, cada um no seu Docker Compose.
- **i5-3330**, 16 GB, SSD SATA 240 GB (o HD foi para o i7 em 2026-10-23), sem GPU → roda Proxmox com a VM do atendente de
  WhatsApp (projeto comercial à parte, em Python) e uma VM de serviços de rede. WireGuard já
  configurado ali, parado desde a mudança de casa. Vai ser desligado (2026-10-18): os serviços vão para o i7.
- O HD de 500 GB avulso estava ruim no teste do Leonardo (2026-10-23): fora de uso. Compra armazenamento se precisar.
- **MacBook**: ambiente de teste (Etapa A).

**Premissas que guiam as decisões**
- Não pagar nada além do que já paga (plano Pro do Claude). Por isso Tailscale e não domínio.
- O servidor é particular justamente para guardar dados sensíveis, inclusive de trabalho, sob controle dele.
- Quer registrar tudo o que for possível; ferramentas e categorias novas surgem com o uso.
- Evolução do banco dirigida pelo uso: quando ele pedir para registrar algo que não existe, um
  modelo competente cria modelo + migração Alembic + ferramentas (ver "Dado novo" no README).
- Execução por modelos: um modelo superior estrutura cada fase, um modelo competente executa cada tarefa.

**Peças que já existem fora deste repo**
- Vault do Obsidian particular, já no modelo "contexto no vault, números no banco", com uma
  prévia de estrutura que ele quer manter ou melhorar. Será migrado para o servidor (fase 2).
- Documento antigo "Assistente Pessoal de IA — Projeto de Implementação" (Claude Docs): era o
  plano vivo do modo antigo. **Este repo passa a ser a fonte da verdade.**
- Ele já usou o **Jev** (TypeSafe AI) como seletor de modelo; entra no gateway do WhatsApp (fase 6).

**Ideias futuras (sem data, só registro)**
- Monitor de rede em casa: ver o que é acessado, consumo, bloquear pelo agente.
- Centralizar o acesso às câmeras de monitoramento.
- Ligação pela operadora (alerta por voz).

---

## Inventário das máquinas (fazer em casa)

Juntar as especificações de **todas** as máquinas e salvar no vault (e um resumo em
`docs/inventario.md`). Para cada máquina:
- Identificação: modelo, função atual, sistema operacional e versão, hostname, IP
- CPU, RAM (quantidade, tipo, slots livres), GPU
- Discos: modelo, capacidade, tipo (SSD/HD), uso, partições, **saúde SMART**
  (`smartctl -a /dev/sdX`: horas ligado, setores realocados/pendentes, desgaste do SSD)
- Rede: interfaces, velocidade
- Serviços/VMs rodando (Proxmox: lista de VMs e recursos de cada uma)
- Observações: defeitos, upgrades possíveis

Comandos úteis (Linux): `lsblk -o NAME,SIZE,MODEL,ROTA,TYPE,MOUNTPOINT`, `sudo smartctl -a /dev/sdX`,
`lscpu`, `free -h`, `sudo dmidecode -t memory`, `ip -br a`, `qm list` (Proxmox).
No Mac: `system_profiler SPHardwareDataType SPStorageDataType`.

---

## Regra de passagem (levar também para o vault)

Vale para todo projeto longo dividido em fases, executado por modelos diferentes:

1. **Ao começar:** ler este arquivo de contexto inteiro antes de qualquer coisa.
2. **Ao terminar uma fase ou tarefa,** o modelo que executou atualiza o arquivo de contexto com:
   - o que foi feito (arquivos, comandos, resultados de teste);
   - o que mudou em relação ao plano e por quê;
   - decisões tomadas e alternativas descartadas;
   - pendências, problemas abertos e o que não foi testado;
   - o estado atual (fase, data, modelo).
3. **E escreve o prompt para o próximo modelo** rodar a etapa seguinte, completo e autossuficiente:
   objetivo, arquivos a ler, critério de pronto, restrições e qual modelo é o indicado.
4. Nada importante fica só na conversa: se foi decidido, vai para o arquivo.

---

## Prompt para a próxima etapa

**Fase 2.1: Paperless único (2026-10-24).** Modelo: Opus 5.5, effort alto (desenho novo, documentos reais depois).
Máquina: Mac para desenhar e testar com dados sintéticos; i7 só quando o Leonardo disser.

```
Leia CONTEXTO.md (entrada 2026-10-24), AGENTS.md, README.md (§ Segunda instância), docs/MIGRACAO.md,
docs/regras-de-negocio.md (fichas que citam o Paperless) e PLANO.md (1b.1, 2.1, 7.3).
Decisão do Leonardo (2026-10-24): um Paperless-ngx só, para ele e para a esposa (instância 1b, ainda não existe),
com um usuário e um token por pessoa; cada assistente só vê os documentos do próprio dono.
Objetivo, nesta ordem:
1. Conferir na documentação do Paperless-ngx (versão fixa) se o isolamento por dono funciona pela API com token
   (permissões de objeto, owner, documentos sem dono). Se não for seguro, pare e diga ao Leonardo.
2. Escrever a ficha em docs/regras-de-negocio.md (status "proposta"): o que o assistente faz com documentos
   (buscar, ler, trocar campos, o que nunca faz), o que acontece com documento sem dono e o que a esposa vê.
   Pedir aprovação antes de implementar.
3. Desenhar o Paperless como projeto Docker Compose próprio (fora do compose do assistente), com pasta própria,
   versão e digest fixos, rede compartilhada com as instâncias do assistente, sem porta fora de 127.0.0.1 e sem
   Funnel. Backup próprio cifrado com age (document_exporter) e ensaio de restauração, como o do assistente.
   Revisar a 7.3 e a trava do exportar/importar (hoje param se houver serviço paperless no compose).
4. Testar com documentos sintéticos no Mac: uv run pytest, ensaio de restauração do Paperless e, pelo app,
   "me mostra o último documento que entrou".
Pronto quando: ficha aprovada; Paperless sobe e restaura no Mac com dados sintéticos; roteiro do i7 escrito em
docs/IMPLANTACAO.md; PLANO e CONTEXTO atualizados; prompt seguinte escrito.
Commit um só, no fim do trabalho, com o ok do Leonardo; o push é ele quem roda. Nada de segredo no repo.
```

**Pendências da implantação no i7 que continuam** (não bloqueiam a 2.1):
1. Teste do ponto no B9, quando o Leonardo terminar os ajustes (ficha antes, se o comportamento mudar).
2. Guardar a identidade do age fora do Mac (só existe em `~/identidade-assistente.txt`).
3. Lint isolado: rodar no i7 os passos do 2b-7 em `docs/IMPLANTACAO.md`, se ainda não rodou.
4. HD do backup: `sudo hdparm -C /dev/sdb` depois de 15 min sem uso (esperado `standby`; senão, `hd-idle`).
5. Confirmar que o launchd do Mac enviou uma sessão real (`consultar_sessoes`).
6. iPhone no Syncthing (Synctrain), depois; inventário do i5 (PLANO 1c.1); consumo (PLANO 1.7).

**Etapa anterior (fechar a implantação no i7), feita em 2026-10-24:** B8, B9 (menos o ponto), ensaio de restauração,
inventário B1 do i7, PLANO 1.9, DNS fixo do servidor depois do reboot; lint isolado no código (falta rodar no i7).

**Etapa anterior (Fase 2b no i7), feita em 2026-10-23.** Modelo: Opus 5.5, effort alto (toca login, vault real e SSH).

```
Leia CONTEXTO.md (entrada 2026-10-21/22), SPRINT_2B.md, AGENTS.md, docs/IMPLANTACAO.md (seção da Fase 2b),
docs/SYNCTHING.md e ferramentas/sessoes/README.md. Máquina: i7 (Debian), com o Leonardo presente.
Objetivo: ligar a Fase 2b em produção na ordem do IMPLANTACAO: vault ligado (VAULT_PATH=/vault, uid 1000,
.git gravável), up -d --build (migrações 0005/0006), scripts/verificar.sh, units novas do vault, deploy key,
gitleaks pull; depois colar a Ficha 1 atual no Projeto "Assistente" e testar o B9 com os exemplos da Ficha 5;
por fim, chave SSH restrita para as sessões e o primeiro enviar.py do Mac.
Pronto quando: verificar.sh tudo ok; os exemplos da Ficha 5 funcionam pelo app; uma sessão do Mac aparece em
consultar_sessoes. Não commitar sem o ok do Leonardo. Nada de segredo no repo.
```

O prompt anterior (sistema completo no PC Windows com dados sintéticos, Fase 2.1/7.3 em diante) continua valendo
depois desta etapa:


Enquanto houver sprint aberta, o prompt de abertura e o passo atual ficam em `SPRINT.md`
(§ Prompt de abertura) e `SPRINT_NOTAS.md` (§ Onde estamos).

**Próxima fase (depois da portabilidade, 2026-10-19): implementar o sistema completo no PC Windows, só com dados
sintéticos.** Modelo: Opus 5.5, effort alto (toca schema e dado). Prompt:

```
Leia CONTEXTO.md (entrada de 2026-10-19), AGENTS.md, README.md, docs/MIGRACAO.md e PLANO.md.
Máquina: PC Windows do trabalho (domínio corporativo), Docker Desktop + Git Bash. Regras desta máquina:
só dados sintéticos; nenhuma credencial real (Google, Pluggy, Tailscale); nada de Tailscale/Funnel nem
porta exposta além de 127.0.0.1; ASSISTENTE_HOME numa pasta de teste fora do repositório.

Objetivo: implementar as fases seguintes do PLANO.md que dão para testar sem dado real, uma tarefa por
vez, começando pela Fase 2.1 (Paperless-ngx no mesmo compose, com bind mounts em data/paperless e
versão/digest fixos) junto com a 7.3 (document_exporter/document_importer no exportar/importar, tirando
a trava que hoje para os scripts quando há o serviço paperless). Depois: Fase 3 (workers), 4.2 e 5.2.
Ficha nova em docs/regras-de-negocio.md antes de comportamento que o Leonardo vê; mudança de tabela só
com migração Alembic revisada à mão.

Pronto quando, a cada tarefa: uv run pytest passa; bash scripts/testes/ensaio_migracao.sh <pasta vazia>
passa (o ensaio cobre o que entrou no pacote); [x] no PLANO.md; CONTEXTO.md atualizado com o que foi
feito, o que não foi testado e o prompt seguinte. Não commitar sem o ok do Leonardo.
``` A "Regra de passagem" acima já
foi levada para o vault em 2026-10-16 (`40-regras/programacao/registro-temporario-de-sprint-na-raiz.md`).
