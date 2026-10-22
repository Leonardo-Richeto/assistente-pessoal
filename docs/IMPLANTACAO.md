# Implantação: teste no MacBook → produção

Sequência combinada: primeiro roda tudo no MacBook até ficar estável; só depois vai para a
máquina dedicada. Marque `[x]` conforme avança.

## Etapa A — Teste no MacBook

- [x] A1. Instalar Docker Desktop (ou OrbStack) e confirmar `docker compose version`
- [x] A2. `git clone https://github.com/Leonardo-Richeto/assistente-pessoal && cd assistente-pessoal`
- [x] A3. Rodar os testes: `cd servidor && uv sync && uv run pytest` (devem passar todos)
- [x] A4 (2026-10-17, standalone). Instalar o Tailscale (se a versão da App Store não aceitar Funnel, usar a standalone);
      no painel, habilitar HTTPS e Funnel para o Mac
- [x] A5 (2026-10-17: `https://<maquina>.<tailnet>.ts.net`, Funnel 443 → 127.0.0.1:8000). `tailscale funnel --bg 8000` → anotar a URL `https://<mac>.<tailnet>.ts.net`
- [x] A6 (2026-10-17: projeto `assistente-pessoal`, cliente Web "assistente teste mac", consentimento externo em teste). Criar um cliente OAuth do Google **de teste** (Google Cloud Console → APIs e serviços → Tela de consentimento OAuth: externo, em teste, com o seu Gmail como usuário de teste → Credenciais → ID do cliente OAuth → Aplicativo da Web)
      - Homepage: URL do A5 · Callback: `<URL do A5>/auth/callback`
- [x] A7 (2026-10-17: `.env` com URL do Funnel, `AUTH_PROVEDOR=google`, credenciais do A6 e `AUTH_DESATIVADA=false`; servidor de pé com login). `cp .env.example .env` e preencher:
      senhas e `JWT_SIGNING_KEY` (`openssl rand -base64 32`), `PUBLIC_BASE_URL` (A5),
      `AUTH_PROVEDOR=google`, credenciais do A6, `GOOGLE_EMAILS_PERMITIDOS=<seu Gmail>`.
      Vault e Paperless vazios por enquanto.
- [x] A8 (2026-10-16, MacBook arm64). `docker compose up -d --build` e `docker compose logs -f servidor` (erro no build → guardar o log)
- [x] A9 (2026-10-17: conector "Assistente (teste Mac)" conectado; "liste as categorias de gasto" respondeu só "teste"). claude.ai → Configurações → Conectores → conector personalizado → `<URL do A5>/mcp` → login Google
- [x] A10 (2026-10-17). Teste pelo iPhone: registrar gasto → consultar → desfazer; registrar ponto → consultar horas
- [x] A11 (2026-10-17: servidor com a cópia em `~/assistente-teste/vault`; 24 ferramentas, busca, leitura e escrita ok no servidor; teste pelo app OK em 2026-10-17). (Opcional) Testar o vault com uma **cópia** do vault em `VAULT_PATH`
- [ ] A12. Usar alguns dias; anotar aqui o que faltou ou incomodou

Observações do teste:
-

## Etapa B — Produção

Só começa com a Etapa A estável. **Máquina decidida (Leonardo, 2026-10-18):** só o i7-6700 fica ligado, com
Debian 12 direto, sem Proxmox; cada serviço roda no seu projeto Docker Compose. O i5 desliga depois que os
serviços dele vierem para o i7 (`PLANO.md` Fase 1c). Backup diário do banco, vault e sessões desde 2026-10-19 (`docs/MIGRACAO.md`). Troque `<usuario>` pelo seu usuário Linux e
`assistente.<tailnet>.ts.net` pelo endereço real (nunca grave o real no repo, que é público).
Scripts: `deploy/inventario.sh`, `scripts/preparar_host.sh`, `scripts/exportar.sh`, `scripts/importar.sh`,
`scripts/verificar.sh`, `deploy/restaurar-banco.sh` (só para os dados do Mac), `deploy/vault/`. Vault e Syncthing:
`docs/SYNCTHING.md`. Backup e migração: `docs/MIGRACAO.md`.

> **Layout novo (2026-10-19, portabilidade):** código em `/srv/assistente/app`, estado em `/srv/assistente`
> (`.env`, `data/`, `vault/`, `backups/`). O Funnel sai de um **container** Tailscale com nome fixo (`TS_NOME`,
> perfil `tailscale`); o Tailscale do host fica só para SSH. Os passos abaixo já estão neste layout.

### Roteiro da implantação

Tempo total estimado: 4h a 5h. Marque conforme avança. A numeração dos passos B segue o `SPRINT.md`;
a **ordem de execução** é a desta lista (B10 vem antes de B8 de propósito: o conector novo só entra
depois de os dados estarem no lugar; B11 e a Fase 2b vêm antes de B8 porque o texto novo da Ficha 1 usa o vault e as
ferramentas da 2b).

0. [x] Pré-condição, cumprida pelo orquestrador: os scripts estão no GitHub (commit e push feitos antes).
   Confira: `git ls-remote https://github.com/Leonardo-Richeto/assistente-pessoal main` e
   `curl -fsI https://raw.githubusercontent.com/Leonardo-Richeto/assistente-pessoal/main/deploy/inventario.sh`
   (deve responder `200`). Se der 404, pare: o push não aconteceu.
1. [ ] (5 min) Ligue o i7 na tomada medidora. A máquina está decidida: i7 com Debian direto (2026-10-18).
2. [ ] (10 min) Inventário no host (B1). No i7, **antes** de apagar o sistema atual.
3. [ ] (40 a 60 min) BIOS, Debian 12 no i7 e economia de energia (B2).
4. [ ] (10 min) Na máquina nova: clonar em `/srv/assistente/app` e rodar `sudo bash scripts/preparar_host.sh` (B3).
5. [ ] (10 min) `sudo tailscale up` do host (só SSH), chave de autenticação para o nó `assistente`, HTTPS e Funnel no painel (B4).
6. [ ] (10 min) Google Cloud Console: acrescentar a URL `https://assistente.<tailnet>.ts.net` ao cliente OAuth (B5).
7. [ ] (15 min) `/srv/assistente/.env` com senhas novas e a chave pública do age, subir a stack com o perfil `tailscale`, `scripts/verificar.sh` (B6, B7).
8. [ ] (2 min) No Mac: `docker compose stop servidor`. O Postgres do Mac fica de pé e nada novo é gravado (B7b).
9. [ ] (30 min) Dados do Mac: backup, `scp`, restaurar em banco novo, conferir, decidir e trocar (B10).
10. [ ] (40 min) Vault e Syncthing e o timer do commit do vault (B11, `docs/SYNCTHING.md`), com `VAULT_PATH=/vault`.
11. [ ] (40 min) Fase 2b no i7: código e migrações, gitleaks, `.gitignore` do vault, timers, deploy key, sessões
    do Claude Code (seção "Fase 2b no i7", abaixo).
12. [ ] (30 min) claude.ai: conector novo, trocar no Projeto "Assistente", colar o texto atual da Ficha 1 (B8) e
    testes, inclusive os da Ficha 5 (B9).
13. [ ] (5 min) Só agora, no Mac: `tailscale funnel --https=443 off` e `docker compose stop` (B9b).
14. [ ] (5 min) Anote o consumo parado (lido no B2c) e comece os 7 dias de medição com a stack (`PLANO.md` 1.7).

> **Aviso:** sem backup do banco (decisão de 2026-10-18), uma falha do SSD do i7 perde todos os
> registros. Olhe a saúde do SSD no inventário (B1) antes de apagar o sistema atual.

### Passos

- [ ] B1. Inventário completo de **todas** as máquinas (só leitura; grava
      `inventario-<hostname>-<AAAA-MM-DD>.md` no diretório atual; nada sai pela rede; falta de ferramenta
      vira "não disponível").
      - **Host Proxmox do i5** (o repo não está lá e o Proxmox não tem sudo): entre como root e rode
        `apt-get install -y smartmontools` e depois
        `curl -fsSLO https://raw.githubusercontent.com/Leonardo-Richeto/assistente-pessoal/main/deploy/inventario.sh && bash inventario.sh`.
      - **i7**: rode **antes de apagar o sistema atual** (se não houver Linux nele, use um pendrive live
        do Debian, instale `smartmontools` e rode o mesmo comando).
      - O arquivo tem hostname e IP: guarde no vault, não no git. Resumo sem dados reais vai para
        `docs/inventario.md` (roteiro em `CONTEXTO.md`).

#### B2. BIOS e Debian 12 no i7

- [ ] B2a. BIOS (`PLANO.md` 1.0): ligue os C-states com o package C-state no máximo e o ASPM. Desligue áudio,
      porta serial e controladoras sem uso. Ligue o "AC power restore", para a máquina voltar sozinha depois
      de queda de luz. Anote o que mudou na nota `maquinas-do-assistente-pessoal` do vault.
- [ ] B2b. Instale Debian 12 direto no i7 (netinst por pendrive): sem ambiente gráfico, "servidor SSH" e
      "utilitários padrão". Disco inteiro no SSD, usuário comum `<usuario>`. **Deixe a senha de root em branco**
      (o instalador instala o `sudo` e põe o usuário no grupo). Se já definiu: `su -`,
      `apt install sudo && usermod -aG sudo <usuario>`, saia e entre de novo. IP fixo, reservado no roteador.
- [ ] B2c. Economia de energia. Por SSH, como `<usuario>`:

```bash
sudo apt-get install -y linux-cpupower powertop
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # antes
sudo tee /etc/systemd/system/economia.service >/dev/null <<'EOF'
[Unit]
Description=Economia de energia: governador powersave e powertop
After=multi-user.target
[Service]
Type=oneshot
ExecStart=/usr/bin/cpupower frequency-set -g powersave
ExecStart=/usr/sbin/powertop --auto-tune
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now economia.service
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # depois: powersave
```

      Se a rede cair ou ficar instável depois disso, apague a linha do `powertop` no serviço e reinicie: o
      `--auto-tune` liga economia na placa de rede, e algumas placas não aguentam. Deixe o i7 parado e anote
      o consumo da tomada (`PLANO.md` 1.7).
      Documentos do Paperless (Fase 2): quando o HD de 500 GB for para o i7 (`PLANO.md` 1c.3), monte-o em
      `/srv/paperless`. O sistema e o Postgres ficam no SSD.

#### Depois do Debian instalado

- [ ] B3. Preparar a máquina. Entre por SSH como `<usuario>`:
      ```bash
      sudo apt-get update && sudo apt-get install -y git
      sudo install -d -o "$USER" -g "$(id -gn)" /srv/assistente
      git clone https://github.com/Leonardo-Richeto/assistente-pessoal /srv/assistente/app
      sudo bash /srv/assistente/app/scripts/preparar_host.sh --dry-run    # leia a saída
      sudo bash /srv/assistente/app/scripts/preparar_host.sh
      ```
      O clone é por HTTPS: o repositório é público, sem credencial. O script recusa se não for Debian 12 ou 13,
      é idempotente, instala Docker + compose, age, Tailscale (host), Syncthing, smartmontools e (só em VM)
      qemu-guest-agent; cria `/srv/assistente/{data,vault,backups,logs}`, o link `app/.env -> ../.env` e o timer
      do backup diário. Não roda `tailscale up`, não mexe no `.env`. Saia e entre de novo na sessão (grupo `docker`).
      Confira: `docker compose version` e o fuso: `timedatectl`. Se não for `America/Sao_Paulo`:
      `sudo timedatectl set-timezone America/Sao_Paulo` (o script só imprime; não muda sozinho).
- [ ] B4. Tailscale. São dois nós:
      - **Host** (administração por SSH): `sudo tailscale up --hostname=<nome-do-host>`. Sem Funnel. Desligue o
        key expiry dele no painel.
      - **Assistente** (container, nome fixo `TS_NOME=assistente`): no painel, Settings → Keys → gere uma
        chave de autenticação (uso único basta) para o `TS_AUTHKEY` do B6. Habilite HTTPS e Funnel na tailnet
        (Funnel liberado para o nó na política de acesso, `nodeAttrs` com `funnel`). Depois que o nó entrar (B7),
        desligue o key expiry dele. A URL fica `https://assistente.<tailnet>.ts.net`, a mesma em qualquer
        máquina e rede.
- [ ] B5. Login. No Google Cloud Console, no cliente OAuth do projeto `assistente-pessoal` (como no Passo 4 da
      Sprint 1), **acrescente** a URL nova: em "Origens JavaScript autorizadas" a
      `https://assistente.<tailnet>.ts.net` e em "URIs de redirecionamento autorizados" a
      `https://assistente.<tailnet>.ts.net/auth/callback`. Não remova as do Mac até a troca terminar.
      A mudança pode levar alguns minutos para valer. Se preferir um cliente de produção separado, crie outro
      e use as credenciais dele. O **desligamento do Mac** é o último passo (B9b), não este.
- [ ] B6. `.env` novo em `/srv/assistente` (`cp /srv/assistente/app/.env.example /srv/assistente/.env`; nunca vai para o git):
      - `ASSISTENTE_HOME=/srv/assistente`, `COMPOSE_PROFILES=tailscale`, `TS_NOME=assistente`, `TS_AUTHKEY` do B4.
      - Senhas novas e diferentes: `SENHA_DONO`, `SENHA_LEITURA`, `SENHA_ESCRITA` e `JWT_SIGNING_KEY`.
        Gere uma por vez: `openssl rand -base64 48`. **Nunca reaproveite as do Mac.**
      - `PUBLIC_BASE_URL=https://assistente.<tailnet>.ts.net`, `AUTH_PROVEDOR=google`, credenciais do Google,
        `GOOGLE_EMAILS_PERMITIDOS=<seu e-mail>`. Sem `AUTH_DESATIVADA`.
      - Chave do age (`docs/MIGRACAO.md` § Chave do age), gerada **fora** do i7: `AGE_DESTINATARIO=age1...`.
        `BACKUP_DESTINO` = pasta do HD externo montado (vazio = mesmo disco).
      - `VAULT_PATH` vazio por enquanto (entra no B11 como `/vault`).
      Proteja o arquivo: `chmod 600 /srv/assistente/.env`. Rode `sudo bash scripts/preparar_host.sh` de novo para
      ligar o timer do backup.
- [ ] B7. Subir: `cd /srv/assistente/app && docker compose up -d --build` (o link `app/.env` aponta para o
      `.env` de fora) e `docker compose logs -f servidor tailscale`. Confira:
      ```bash
      bash scripts/verificar.sh      # serviços, consulta pelo MCP, /mcp local = 401 e Funnel = 401
      curl -s https://assistente.<tailnet>.ts.net/.well-known/oauth-protected-resource/mcp   # responde
      ```
      Se o `/mcp` responder 200 sem token: **pare**, `docker compose stop tailscale` e investigue. Depois que o nó
      entrar, apague o valor de `TS_AUTHKEY` do `.env` (a identidade fica em `data/tailscale`).
- [ ] B7b. No Mac, pare só o servidor: `cd ~/Desktop/Projetos/assistente-pessoal && docker compose stop servidor`.
      O Postgres do Mac continua de pé (o backup do B10 precisa dele) e nada novo é gravado.
- [ ] B10. Decidir se os registros do Mac vão para a produção ou se começa limpo. Para levar:
      1. No Mac, na pasta do projeto (o Postgres de pé, o servidor parado pelo B7b), **sem atualizar o código do
         Mac antes** (o compose novo não enxerga os volumes antigos; ver `docs/MIGRACAO.md` § Limites):
         `git show 8d2ec8d:deploy/backup-banco.sh > /tmp/backup-banco.sh && BACKUP_DIR=~/backup-mac bash /tmp/backup-banco.sh`
      2. Copie: `scp ~/backup-mac/assistente-<data>.dump <usuario>@<maquina>:/tmp/`
      3. Na produção, restaure num banco **novo** (o script recusa o nome `assistente`):
         `bash /srv/assistente/app/deploy/restaurar-banco.sh /tmp/assistente-<data>.dump assistente_mac`
         e confira a contagem de linhas impressa (gastos, ponto, auditoria) contra o Mac.
      4. Só então decida. Para adotar os dados, com aviso: isto troca o banco que o servidor usa.
         ```bash
         docker compose stop servidor
         docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres \
           -c "ALTER DATABASE assistente RENAME TO assistente_vazio" \
           -c "ALTER DATABASE assistente_mac RENAME TO assistente"'
         docker compose up -d
         ```
         O banco vazio fica como `assistente_vazio` (nada é apagado). Repita o 401 e um teste de consulta.
         Se o `RENAME` reclamar de conexões abertas, espere alguns segundos e repita.
         **Se o primeiro `ALTER` passar e o segundo falhar**, o servidor fica sem banco `assistente`. Não entre
         em pânico e não apague nada. Veja o estado:
         `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -l'`.
         - Existem `assistente_vazio` e `assistente_mac`, e não existe `assistente`: rode só o segundo `ALTER`
           (`... RENAME TO assistente` sobre `assistente_mac`).
         - Existe `assistente` e não existe `assistente_vazio`: nada mudou, repita desde o primeiro `ALTER`.
         Depois `docker compose up -d`.
      5. Para começar limpo: apague o banco de conferência com
         `docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" assistente_mac'`.
- [ ] B8. **Antes:** B11 feito (vault ligado, `VAULT_PATH=/vault`) e a seção "Fase 2b no i7" feita (servidor da 2b
      de pé). No claude.ai: Configurações → Conectores → adicionar conector personalizado `https://assistente.<tailnet>.ts.net/mcp`
      e entrar com o Google. No Projeto "Assistente": trocar o conector do Mac pelo novo. Depois remova o conector
      de teste. **Nas instruções do Projeto, troque o texto inteiro** pelo texto atual da Ficha 1 (com a Ficha 5):
      o bloco "Texto proposto" de `docs/regras-de-negocio.md`, com "o dono" trocado por "Leonardo" e a 1ª frase
      "Você é o assistente pessoal do Leonardo, dono deste Projeto." Tem as Fichas 3, 4 e 5, ainda não coladas.
      **Suba o servidor da 2b e cole o texto no mesmo momento.** O texto novo cita ferramentas que só existem na 2b
      (`buscar_vault`, `ler_nota`, `escrever_nota`...). O servidor da 2b recusa `vault_write_note` sem `mode`, que o
      texto antigo usava. Servidor velho com texto novo, ou o contrário, quebra a escrita no vault.
- [ ] B9. Repetir os testes do A10 pelo iPhone (gasto → consultar → desfazer; ponto → horas). Testar também as
      Fichas 3 e 4: "estudei X 1 h e aprendi Y" anota em `50-diario/AAAA/AAAA-MM-DD.md`, seção "Pelo assistente";
      "registra o que fizemos" escreve o resumo na mesma nota; `python3 -I /srv/assistente/vault/90-meta/lint-do-vault.py` sem ERRO.
      Depois, os exemplos da Ficha 5. Antes, crie no Obsidian do Mac uma nota de teste `00-inbox/teste-2b.md` com
      duas linhas e espere ela chegar ao i7 (`ls /srv/assistente/vault/00-inbox/`).
      - [ ] Busca: "O que eu decidi sobre o carro?" (ou outro assunto do vault). Responde citando a nota certa.
      - [ ] Reescrever com versão: "Reescreve a nota 00-inbox/teste-2b.md com o texto: linha nova". Responde
            "Reescrevi 00-inbox/teste-2b.md." No i7: `git -C /srv/assistente/vault log --oneline -3 -- 00-inbox/teste-2b.md`
            mostra um commit `claude-app`.
      - [ ] Nota que mudou no meio: peça "Lê a nota 00-inbox/teste-2b.md". Mude uma linha dela no Obsidian do Mac e
            espere o Syncthing. Peça "Reescreve essa nota com o texto: outra linha". Ele lê de novo e pergunta: "A nota
            mudou no meio. Quer que eu aplique sobre a versão nova?"
      - [ ] Segredo recusado: "Anota na nota do dia que a senha do roteador é Casa-Teste-2026x". Nada é gravado com o
            valor; ele oferece `{{segredo:roteador}}`. Confira: `grep -r "Casa-Teste" /srv/assistente/vault` não acha
            nada.
      - [ ] Histórico e restaurar: "Volta a nota 00-inbox/teste-2b.md para a versão anterior". Ele mostra as versões
            (`historico_nota`), pergunta qual e responde "Restaurei 00-inbox/teste-2b.md para a versão de AAAA-MM-DD HH:MM."
            A restauração é um commit novo; nada some do histórico.
      - [ ] Marcar desatualizada: "A nota 00-inbox/teste-2b.md está velha". Responde "Marquei como desatualizada (id N).
            Desfazer?". Responda "sim" e confira que desfez. Marque de novo para ver no lint do dia seguinte
            (`/srv/assistente/logs/vault-lint/ultimo.md`, seção "Notas marcadas como desatualizadas").
      - [ ] `contexto_inicial`: abra conversa nova com "Como está o meu trabalho?". Ele chama `contexto_inicial` uma
            vez (confira com "consulte as chamadas de hoje") e responde com o "Trabalho em andamento" do `onde-parei.md`.
            Em "gastei 30 no mercado", não chama.
      - [ ] `consultar_sessoes` (depois do primeiro envio das sessões, seção "Fase 2b no i7"): "O que eu fiz no Claude
            Code esta semana?". Responde com projeto, máquina e horário das sessões.
      No fim, apague a nota de teste no Obsidian do Mac (o histórico fica no git).
- [ ] B9b. Só depois de B8 e B9 funcionarem, desligue o Mac:
      ```bash
      tailscale funnel --https=443 off                                  # no Mac (sudo, se pedir)
      cd ~/Desktop/Projetos/assistente-pessoal && docker compose stop   # sem -v, os dados do Mac ficam
      ```
- [ ] B11. Vault e Syncthing: siga `docs/SYNCTHING.md` (Syncthing como serviço, pasta `/srv/assistente/vault`, aparelhos,
      versionamento Staggered com as versões em `/srv/assistente/data/vault-versoes`, `.gitignore` do vault, timer do
      commit às 03:30, `VAULT_PATH=/vault` no `.env`). **Não verificado:** se o Synctrain aceita padrões de ignorar, e se o
      Obsidian do iPhone abre a pasta do Synctrain.
      **Aviso (2b.4):** o servidor comita cada escrita da IA no `.git` do vault com o uid 1000 do container. Confira o
      dono antes de subir: `stat -c %u /srv/assistente/vault/.git /srv/assistente/vault/.git/objects` tem de dar `1000`.
      Se der outro uid sem escrita para o 1000, o commit por escrita falha (só WARNING em `docker compose logs servidor`; a escrita vale e o
      commit das 03:30 leva a mudança), e a escrita da IA numa nota que o dono mudou sem commit é recusada (a foto do
      estado anterior não sai). Avise antes de mudar `chown`.
      O usuário do commit diário e do Syncthing (`<usuario>`) precisa ter uid 1000, o mesmo do container:
      `id -u <usuario>` deve dar 1000. Conferir: `find /srv/assistente/vault/.git ! -uid 1000 | head` não mostra nada.
      **Ordem:** o B11 vem antes do B8. O texto novo da Ficha 1 manda o Claude ler e escrever no vault.

#### Fase 2b no i7 (depois do B11, antes do B8)

O código da Fase 2b fica na branch `fase-2b` até o merge em `main` (decisão sua). Faça o merge e o push antes deste
passo: o i7 clona o `main`. A ordem: código e banco, gitleaks, `.gitignore` do vault, timers, deploy key, sessões.
Neste roteiro, o conector do i7 só entra no B8, junto com o texto novo da Ficha 1: o servidor da 2b e o texto novo
chegam ao app juntos. Se o i7 já estiver em uso com o texto antigo, faça o 2b-1 e o B8 no mesmo momento (veja o aviso
no B8).

- [ ] 2b-1. Código e migrações. No i7:
      ```bash
      cd /srv/assistente/app && git pull && docker compose up -d --build
      bash scripts/verificar.sh
      ```
      O serviço `migracao` roda sozinho no `up -d --build`, antes do servidor, e sobe as migrações 0005
      (`notas_desatualizadas`) e 0006 (`sessoes`). O `verificar.sh` deve mostrar `migracao terminou com 0`,
      `migração do banco na cabeça (0006)`, `tabela notas_desatualizadas legível pela leitura`,
      `tabela sessoes legível pela leitura`, `vault: N notas indexadas` e `vault: .git gravável`. Se o banco não
      estiver na 0006, pare e veja `docker compose logs migracao`.
- [ ] 2b-2. Imagem do gitleaks, com o digest fixo do `deploy/vault/commit-diario.sh` (`GITLEAKS_IMAGE`). Baixe agora:
      o commit diário roda às 03:30 e, sem a imagem, depende da rede naquela hora.
      ```bash
      docker pull ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
      grep -o 'gitleaks:v[^}"]*' /srv/assistente/app/deploy/vault/commit-diario.sh   # tem de ser o mesmo texto
      ```
      Se os dois forem diferentes, use o do script: ele vale.
- [ ] 2b-3. `.gitignore` do vault atualizado a partir de `deploy/vault/gitignore-do-vault`. As linhas novas são
      `.obsidian/plugins/*/data.json` (plugins guardam chave de API ali) e `.escrever-nota-*.tmp` (temporário do
      `escrever_nota`). O comando acrescenta só as linhas que faltam:
      ```bash
      cd /srv/assistente/vault
      while IFS= read -r l; do
        case "$l" in ''|'#'*) continue ;; esac
        grep -qxF -- "$l" .gitignore 2>/dev/null || printf '%s
' "$l" >>.gitignore
      done </srv/assistente/app/deploy/vault/gitignore-do-vault
      git diff .gitignore                                    # confira
      git ls-files '.obsidian/plugins/*/data.json'           # não deve listar nada
      ```
      O commit diário comita o `.gitignore`. Se o `ls-files` listar algum `data.json`, ele já está no histórico
      (e no GitHub). Avise antes de mexer: tirar do git é decisão sua.
- [ ] 2b-4. Units novas (`vault-marcas.*`) e atualizadas (`vault-commit.service`, `vault-lint.service`: ordem depois
      do backup, carimbo de execução limpa). O `cp` sobrescreve as do B11; o `sed` põe o usuário de novo.
      ```bash
      cd /srv/assistente/app/deploy/vault
      sudo cp vault-commit.service vault-commit.timer vault-lint.service vault-lint.timer         vault-marcas.service vault-marcas.timer /etc/systemd/system/
      sudo sed -i "s/<usuario>/$USER/" /etc/systemd/system/vault-commit.service         /etc/systemd/system/vault-lint.service /etc/systemd/system/vault-marcas.service
      sudo install -d -o "$USER" -g "$USER" /srv/assistente/logs/vault-commit /srv/assistente/logs/vault-lint
      sudo systemctl daemon-reload
      sudo systemctl enable --now vault-commit.timer vault-marcas.timer vault-lint.timer
      systemctl list-timers 'vault-*' assistente-backup.timer   # 03:15 backup, 03:30, 03:35, 03:40
      systemctl show -p After vault-lint.service                # cita vault-commit.service e vault-marcas.service
      ```
- [ ] 2b-5. Deploy key do vault. O push usa `~/.ssh/vault_deploy` do `<usuario>` (B11, `docs/SYNCTHING.md` seção 2)
      ou o caminho em `VAULT_SSH_CHAVE`, no `/etc/default/vault-commit`. Não precisa de `core.sshCommand` no
      repositório: o script ignora a config do `.git`. Teste o serviço inteiro:
      ```bash
      ls -l ~/.ssh/vault_deploy
      sudo systemctl start vault-commit.service
      journalctl -u vault-commit.service -n 20 --no-pager        # com VAULT_PUSH=1: "push feito (... para main)"
      ls -l /srv/assistente/logs/vault-commit/ultima-execucao-ok # -rw-r--r--, hora de agora
      sudo systemctl start vault-marcas.service && sudo systemctl start vault-lint.service
      head -20 /srv/assistente/logs/vault-lint/ultimo.md
      ```
      Se o journal disser "não achei a chave de deploy", confira o caminho; sem a chave, o commit fica só local.
- [ ] 2b-6. Sessões do Claude Code (Ficha 5, regra 9). Detalhe em `ferramentas/sessoes/README.md`. Só o Mac envia;
      o PC do trabalho, sem Tailscale, fica só com a fila local.
      1. No i7, um usuário só para receber o envio, no grupo `docker` (recomendado no README):
         ```bash
         sudo adduser --disabled-password --gecos '' sessoes
         sudo usermod -aG docker sessoes
         sudo install -d -m 700 -o sessoes -g sessoes /home/sessoes/.ssh
         docker ps --filter label=com.docker.compose.service=servidor --format '{{.Names}}'   # assistente-servidor-1
         ```
      2. No Mac, a chave só do envio (se ainda não existe):
         `ssh-keygen -t ed25519 -f ~/.ssh/assistente_sessoes -N '' -C assistente-sessoes`.
      3. No i7, a chave restrita em `/home/sessoes/.ssh/authorized_keys` (dono `sessoes`, modo 600), com o conteúdo de
         `~/.ssh/assistente_sessoes.pub` do Mac no lugar de `ssh-ed25519 AAAA...` e o nome do container do passo 1:
         ```
         restrict,command="docker exec -i assistente-servidor-1 python -m assistente.sessoes importar" ssh-ed25519 AAAA... assistente-sessoes
         ```
         É `docker exec`, não `docker compose exec`: o `docker compose` lê o `.env` (modo 600, seu), e o usuário
         `sessoes` não lê.
      4. No Mac, aceite a host key do i7 uma vez (o envio usa `BatchMode=yes` e nunca pergunta):
         `ssh -n -i ~/.ssh/assistente_sessoes -o IdentitiesOnly=yes sessoes@<host-do-i7> true`. Responda `yes`. A
         resposta esperada é `{"aceitas": [], "repetidas": [], "recusadas": []}`.
      5. No Mac, envie o que está na fila, com `ASSISTENTE_SSH` no formato `usuario@maquina`:
         `ASSISTENTE_SSH=sessoes@<host-do-i7> /usr/bin/python3 ferramentas/sessoes/enviar.py`.
      6. Os hooks (`instalar.py`) já estão instalados no Mac desde 2026-10-22. Confira com
         `/usr/bin/python3 ferramentas/sessoes/instalar.py --mostrar`.
      7. Opcional: envio a cada hora pelo launchd (plist em `ferramentas/sessoes/exemplos/`, passos em "Agendar no
         Mac" do README). Sem ele, rode o passo 5 à mão.
- [ ] 2b-7. Pendências que são decisão sua (anote a decisão aqui):
      - Usuário próprio para o lint, fora do grupo `docker`. Hoje o `vault-lint.service` usa o mesmo `<usuario>` do
        commit e das marcas, que está no grupo `docker`; o código do lint vem do vault, pelo Syncthing.
      - Rever o bloqueio de `vault_move_note` e `vault_move_file`, depois de usar o histórico (2b.4) alguns dias.
      - Vaultwarden (2b.3a), depois do backup ligado (B12).
- [ ] B12. Backup diário (2026-10-19, portabilidade; substitui o adiamento de 2026-10-18): o `preparar_host.sh` já
      instalou o `assistente-backup.timer`. Confira `systemctl list-timers assistente-backup.timer`, rode uma vez à mão
      (`sudo systemctl start assistente-backup.service`, `journalctl -u assistente-backup -n 30`) e faça um ensaio de
      restauração (`docs/MIGRACAO.md` § Ensaio). Guarde a identidade do age fora do i7.
- [ ] B13. Seguir para a Fase 2 do `PLANO.md` (Paperless).
