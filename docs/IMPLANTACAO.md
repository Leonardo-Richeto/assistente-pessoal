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
Debian 13 direto (hoje com Windows, que será apagado; o 12 saiu do suporte normal em 2026-06), sem Proxmox; cada serviço roda no seu projeto Docker Compose. O i5 desliga depois que os
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
1. [x] (5 min) Ligue o i7 na tomada medidora. Feito em 2026-10-28 (11,5 a 15 W logo depois de religar). A máquina está decidida: i7 com Debian direto (2026-10-18).
2. [x] (10 min) Inventário no host (B1). No i7, depois do B2d (o SMART não se apaga ao formatar). Feito em 2026-10-24 (`docs/inventario.md`).
3. [x] (40 a 60 min) BIOS, Debian 13 no i7, economia de energia, SMART e HD do backup (B2).
4. [x] (10 min) Na máquina nova: clonar em `/srv/assistente/app` e rodar `sudo bash scripts/preparar_host.sh` (B3).
5. [x] (10 min) `sudo tailscale up` do host (só SSH), chave de autenticação para o nó `assistente`, HTTPS e Funnel no painel (B4).
6. [x] (10 min) Google Cloud Console: acrescentar a URL `https://assistente.<tailnet>.ts.net` ao cliente OAuth (B5).
7. [x] (15 min) `/srv/assistente/.env` com senhas novas e a chave pública do age, subir a stack com o perfil `tailscale`, `scripts/verificar.sh` (B6, B7).
8. [x] (2 min) No Mac: `docker compose stop servidor`. O Postgres do Mac fica de pé e nada novo é gravado (B7b).
9. [x] (30 min) Dados do Mac: backup, `scp`, restaurar em banco novo, conferir, decidir e trocar (B10). Decidido em
   2026-10-23 (Leonardo): começar limpo; o Mac só tinha teste (7 gastos, 2 pontos). O volume do Mac fica guardado.
10. [x] (40 min) Vault e Syncthing e o timer do commit do vault (B11, `docs/SYNCTHING.md`), com `VAULT_PATH=/vault`.
11. [x] (40 min) Fase 2b no i7 (menos o 2b-7, decisões pendentes): código e migrações, gitleaks, `.gitignore` do vault, timers, deploy key, sessões
    do Claude Code (seção "Fase 2b no i7", abaixo).
12. [x] (B8 feito em 2026-10-24; B9 em 2026-10-30) (30 min) claude.ai: conector novo, trocar no Projeto "Assistente", colar o texto atual da Ficha 1 (B8) e
    testes, inclusive os da Ficha 5 (B9).
13. [ ] (5 min) Só agora, no Mac (o Funnel do Mac já estava sem configuração em 2026-10-23; o servidor do Mac, parado): `tailscale funnel --https=443 off` e `docker compose stop` (B9b).
14. [ ] (5 min) Comece os 7 dias de medição com a stack inteira (`PLANO.md` 1.7). Sem medição do i7 parado (2026-10-28).

> **Feito em 2026-10-23 (Opus 5.5 guiando do Mac):** passos 3 a 11. Lições: o Syncthing 2 não cria "Default Folder" nem
> mostra a aba de ignorar ao criar a pasta (ponha o `.stignore` na raiz antes); no Mac, o caminho da pasta vai completo
> (`/Users/...`, sem `~`); o primeiro sync gera um `.sync-conflict` do `.gitignore` (fica a versão nova; apague a cópia);
> o DNS público do Funnel levou ~20 min para aparecer depois de reiniciar o container do Tailscale.
>
> **Backup desde o início (Leonardo, 2026-10-23):** o backup diário cifrado vai para o HD de 500 GB (B2d). Gere a chave
> do age no Mac antes do B6 (`docs/MIGRACAO.md` § Chave do age). O HD fica na mesma máquina: não protege de roubo,
> raio ou fonte queimada.

### Passos

- [ ] B1. Inventário completo de **todas** as máquinas (só leitura; grava
      `inventario-<hostname>-<AAAA-MM-DD>.md` no diretório atual; nada sai pela rede; falta de ferramenta
      vira "não disponível").
      - **Host Proxmox do i5** (o repo não está lá e o Proxmox não tem sudo): entre como root e rode
        `apt-get install -y smartmontools` e depois
        `curl -fsSLO https://raw.githubusercontent.com/Leonardo-Richeto/assistente-pessoal/main/deploy/inventario.sh && bash inventario.sh`.
      - **i7** (hoje com Windows): o SMART não se apaga ao formatar, então rode no Debian já instalado, depois
        do B2d. Antes de formatar, confira o SSD no CrystalDiskInfo (B2a, item 0).
      - O arquivo tem hostname e IP: guarde no vault, não no git. Resumo sem dados reais vai para
        `docs/inventario.md` (com o roteiro).

#### B2. BIOS e Debian 13 no i7

- [ ] B2a. BIOS (`PLANO.md` 1.0). Os nomes mudam conforme o fabricante; procure pelo sentido.
      0. Ainda no Windows: se o fabricante tiver BIOS mais nova, atualize agora (o atualizador costuma ser só
         para Windows). Confira o SSD no CrystalDiskInfo; se aparecer "Ruim", pare.
      1. Ligue: C-states, C1E, package C-state no máximo (C8 ou "No limit"), SpeedStep (EIST), Speed Shift,
         ASPM (PCIe, PCH, DMI), SATA em **AHCI** e o link power management do SATA, se existir.
      2. Desligue: áudio, porta serial e paralela, Wi-Fi e Bluetooth (se houver), LEDs, XMP da RAM.
      3. Deixe ligados: o vídeo da CPU (a instalação precisa dele uma vez), VT-x, boot UEFI.
      4. "Restore on AC power loss" em **Power On**: a máquina volta sozinha depois de queda de luz.
      5. "Halt on" em "No errors" (ou desligue o erro de teclado ausente): o i7 vai ligar sem teclado e sem monitor.
      6. Se ligar ErP/EuP (espera profunda): tire o i7 da tomada e ponha de volta; ele tem de ligar sozinho.
      No i7 (HP EliteDesk 800 G2, placa 8054, BIOS 2.60): F10 no boot; quase tudo em Advanced → Power Management
      Options (Runtime Power Management, Extended Idle Power States, SATA e PCI Express Power Management),
      Built-In Device Options (áudio, vídeo) e Boot Options (After Power Loss).
      Anote o que mudou na nota `maquinas-do-assistente-pessoal` do vault.
- [ ] B2b. Instale Debian 13 direto no i7 (netinst amd64 por pendrive): sem ambiente gráfico, "servidor SSH" e
      "utilitários padrão". Disco inteiro no SSD (escolha pelo modelo; **não** o HD), usuário comum `<usuario>`. **Deixe a senha de root em branco**
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
      `--auto-tune` liga economia na placa de rede, e algumas placas não aguentam. O consumo se mede só com a stack
      inteira (`PLANO.md` 1.7).
      Confira se o processador desce a estados fundos: `sudo powertop`, aba "Idle stats", deve chegar a Pkg C6
      ou mais. Se parar em C2 ou C3, alguma peça está sem ASPM (a placa de rede é a suspeita comum).
- [ ] B2d. SMART e HD do backup (2026-10-23: o HD de 500 GB do i5 foi para o i7; o HD avulso estava ruim). O
      sistema, o Postgres, o vault e o Paperless ficam no SSD; o HD guarda só o backup (`BACKUP_DESTINO`).
      O SMART não se apaga ao formatar, então o teste roda aqui. Troque `sdX` pelo nome que o `lsblk` mostrar.

```bash
sudo apt-get install -y smartmontools parted hdparm
lsblk -o NAME,SIZE,MODEL,ROTA,MOUNTPOINT        # SSD: ROTA=0, com o sistema; HD: ROTA=1, ~465G, sem uso
sudo smartctl -t long /dev/sdX                  # nos dois discos; SSD ~10 min, HD 80 a 120 min
sudo smartctl -a /dev/sdX                       # depois do tempo: "Completed without error" e os atributos
```

      Descarte o disco se: HD com atributo 5, 197 ou 198 acima de 0; SSD com 5 ou 187 acima de 0 ou vida restante
      abaixo de ~20% (177, 231 ou 233, conforme a marca); teste longo com erro. Atributo 199 subindo é cabo SATA.
      Depois rode o inventário (B1) no i7.

      **Aviso:** os comandos abaixo apagam o HD inteiro. Antes, confira que nada do i5 (VMs, banco do
      agente-whatsapp) existe só nesse HD, e que `/dev/sdX` é o HD (ROTA=1), não o SSD do sistema.

```bash
sudo parted -s /dev/sdX mklabel gpt mkpart backup ext4 0% 100%
sudo mkfs.ext4 -L backup /dev/sdX1
sudo install -d /srv/backup-hd && sudo chattr +i /srv/backup-hd   # sem o HD montado, ninguém grava no SSD
echo 'LABEL=backup /srv/backup-hd ext4 defaults,nofail,noatime,x-systemd.device-timeout=10s 0 2' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/backup-hd
sudo chown "$USER": /srv/backup-hd && df -h /srv/backup-hd
ls /dev/disk/by-id/ | grep -v -- -part          # ache o ata-... do HD
printf '/dev/disk/by-id/<ata-do-HD> {\n    spindown_time = 120\n}\n' | sudo tee -a /etc/hdparm.conf   # para em 10 min
```

      `nofail`: o servidor liga mesmo se o HD morrer. **Não verificado:** se o HD obedece o `spindown_time`
      (confira com `sudo hdparm -C /dev/sdX` depois de 10 min parado: `standby`); se não obedecer, use o `hd-idle`.

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
        `BACKUP_DESTINO=/srv/backup-hd` (o HD do B2d; vazio = mesmo disco).
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
      **Nunca reinicie só o `servidor`** (`docker compose restart servidor`): o Tailscale usa a rede dele
      (`network_mode: service:servidor`) e fica preso na rede velha; o Funnel cai (2026-10-24). Para reiniciar:
      `docker compose up -d --force-recreate servidor tailscale`. Depois de recriar o Tailscale, o nome do Funnel
      pode sumir do DNS público por alguns minutos.
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
- [x] B8. (2026-10-24: Projeto recriado; no claude.ai novo ele roda no Claude Code, ver o registro de 2026-10-24 no vault.) **Antes:** B11 feito (vault ligado, `VAULT_PATH=/vault`) e a seção "Fase 2b no i7" feita (servidor da 2b
      de pé). No claude.ai: Configurações → Conectores → adicionar conector personalizado `https://assistente.<tailnet>.ts.net/mcp`
      e entrar com o Google. No Projeto "Assistente": trocar o conector do Mac pelo novo. Depois remova o conector
      de teste. **Nas instruções do Projeto, troque o texto inteiro** pelo texto atual da Ficha 1 (com a Ficha 5):
      o bloco "Texto proposto" de `docs/regras-de-negocio.md`, com "o dono" trocado por "Leonardo" e a 1ª frase
      "Você é o assistente pessoal do Leonardo, dono deste Projeto." Tem as Fichas 3, 4 e 5, ainda não coladas.
      **Suba o servidor da 2b e cole o texto no mesmo momento.** O texto novo cita ferramentas que só existem na 2b
      (`buscar_vault`, `ler_nota`, `escrever_nota`...). O servidor da 2b recusa `vault_write_note` sem `mode`, que o
      texto antigo usava. Servidor velho com texto novo, ou o contrário, quebra a escrita no vault.
- [x] B9. (2026-10-30: rodada única pelo app, sem erro, relatada pelo Leonardo.) Repetir os testes do A10 pelo iPhone (gasto → consultar → desfazer; ponto → horas). Testar também as
      Fichas 3 e 4: "estudei X 1 h e aprendi Y" anota em `50-diario/AAAA/AAAA-MM-DD.md`, seção "Pelo assistente";
      "registra o que fizemos" escreve o resumo na mesma nota; `python3 -I /srv/assistente/vault/90-meta/lint-do-vault.py` sem ERRO.
      Depois, os exemplos da Ficha 5. Antes, crie no Obsidian do Mac uma nota de teste `00-inbox/teste-2b.md` com
      duas linhas e espere ela chegar ao i7 (`ls /srv/assistente/vault/00-inbox/`).
      - [ ] Busca: "O que eu decidi sobre o carro?" (ou outro assunto do vault). Responde citando a nota certa.
      - [ ] Reescrever com versão: "Reescreve a nota 00-inbox/teste-2b.md com o texto: linha nova". Responde
            "Reescrevi 00-inbox/teste-2b.md." No i7: `git -C /srv/assistente/vault log --oneline -3 -- 00-inbox/teste-2b.md`
            mostra um commit `claude-app`.
      - [x] (2026-10-24: releu, viu "Segunda mudança." e perguntou; nada gravado) Nota que mudou no meio: peça "Lê a nota 00-inbox/teste-2b.md". Mude uma linha dela no Obsidian do Mac e
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
- [x] B9b. (2026-10-24: nenhum container no Mac; o Funnel do Mac já estava sem configuração em 2026-10-23.) Só depois de B8 e B9 funcionarem, desligue o Mac:
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
      - [x] Lint isolado (Leonardo, 2026-10-24: fazer já; feito e provado no i7 às 12:55, nota 3.8 OK). Em vez de um usuário novo, o `vault-lint.service` roda numa
        caixa do systemd: sem rede, sem socket, sem o socket do docker, sem sudo, disco só leitura, grava só o
        `LINT_DIR`. No i7, depois do `git pull`:
        ```bash
        cd /srv/assistente/app/deploy/vault
        sudo cp vault-lint.service /etc/systemd/system/ && sudo sed -i "s/<usuario>/$USER/" /etc/systemd/system/vault-lint.service
        sudo systemctl daemon-reload && sudo systemctl start vault-lint.service
        systemctl status vault-lint.service --no-pager | head -5; head -3 /srv/assistente/logs/vault-lint/ultimo.md
        systemd-analyze security vault-lint.service --no-pager | grep -E 'RestrictAddressFamilies|PrivateNetwork|Overall'
        # Prova: o mesmo usuário, com as travas, não fala com o docker nem com a internet (o systemd-run não aceita
        # RestrictAddressFamilies=none; a unit aceita, e o systemd-analyze acima mostra que ela aplicou).
        sudo systemd-run --wait --pipe -q -p User=$USER -p InaccessiblePaths=/run/docker.sock docker ps; echo "docker: código $?"
        sudo systemd-run --wait --pipe -q -p User=$USER -p PrivateNetwork=yes curl -sS -m 5 https://1.1.1.1 -o /dev/null; echo "internet: código $?"
        # esperado: os dois diferentes de 0 ("permission denied" no docker, "Could not connect" no curl)
        ```
      - Rever o bloqueio de `vault_move_note` e `vault_move_file` em 2026-11-07, depois de duas semanas de histórico
        (recomendação aceita sem objeção pelo Leonardo, 2026-10-24).
      - Vaultwarden (2b.3a): depois do Paperless (recomendação aceita sem objeção, 2026-10-24). Ele não guarda a identidade do age: o backup
        dele sai cifrado com ela.
- [x] B12. (2026-10-24: timer rodou às 03:18, ensaio ok com `scripts/ensaiar_restauracao.sh`; identidade só no Mac, cópia fora pendente.) Backup diário (2026-10-19, portabilidade; substitui o adiamento de 2026-10-18): o `preparar_host.sh` já
      instalou o `assistente-backup.timer`. Confira `systemctl list-timers assistente-backup.timer`, rode uma vez à mão
      (`sudo systemctl start assistente-backup.service`, `journalctl -u assistente-backup -n 30`) e faça um ensaio de
      restauração (`docs/MIGRACAO.md` § Ensaio). Guarde a identidade do age fora do i7.
- [ ] B13. Seguir para a Fase 2 do `PLANO.md` (Paperless).

#### Fase 2.1 no i7: Paperless único (Ficha 6)

Um Paperless-ngx só para o Leonardo e a Nathalia, como projeto Docker Compose próprio (`paperless/`), fora do
compose do assistente. Cada pessoa tem um usuário comum e um token; cada assistente só vê os documentos do dono.
Ensaiado no Mac em 2026-10-24 com documentos sintéticos (isolamento, workflows, backup e restauração).
Lê PDF, imagem, Word, Excel, PowerPoint, OpenDocument e e-mail (`.eml`): o Tika extrai o texto e o
Gotenberg gera o PDF de visualização; o original fica guardado. Gasta ~1,5 GB de RAM (medido no Mac: webserver 1 GB,
Tika 0,3 GB, Gotenberg 0,15 GB). **Antes:** a chave pública do age (a mesma do assistente) e ~15 min.

- [x] P1 (2026-10-24). Estado e `.env` (senhas novas; nunca as do Mac):
      ```bash
      sudo mkdir -p /srv/paperless && sudo chown <usuario>: /srv/paperless && chmod 700 /srv/paperless
      cp /srv/assistente/app/paperless/.env.example /srv/paperless/.env && chmod 600 /srv/paperless/.env
      nano /srv/paperless/.env   # PAPERLESS_DBPASS, PAPERLESS_SECRET_KEY, PAPERLESS_ADMIN_PASSWORD (openssl rand -hex 32),
                                 # AGE_DESTINATARIO e BACKUP_DESTINO=/srv/backup-hd/paperless
      ```
      Guarde a senha do admin no gerenciador de senhas. `PAPERLESS_CONSUMER_POLLING` fica 0 no Linux.
- [x] P2 (2026-10-24). Subir e preparar (baixa ~2 GB de imagens e o idioma `por` na primeira vez):
      ```bash
      cd /srv/assistente/app && PAPERLESS_HOME=/srv/paperless bash paperless/scripts/preparar.sh
      ```
      Esperado no fim: `conferir: ok`, `porta: 127.0.0.1:8010 (só loopback)` e `preparar: pronto`. Se a conferência
      achar problema, o script para; leia as linhas `PROBLEMA`.
- [x] P3 (2026-10-24). Ligar o assistente do Leonardo. O token é segredo: vai direto do comando para o `.env`, sem aparecer na tela:
      ```bash
      T="$(PAPERLESS_HOME=/srv/paperless bash paperless/scripts/token.sh leonardo)"
      sed -i "s|^PAPERLESS_API_KEY=.*|PAPERLESS_API_KEY=$T|; s|^PAPERLESS_URL=.*|PAPERLESS_URL=http://paperless:8000|" /srv/assistente/.env
      unset T
      grep -q '^COMPOSE_FILE=' /srv/assistente/.env \
        || echo 'COMPOSE_FILE=docker-compose.yml:deploy/paperless/rede.yml' >> /srv/assistente/.env
      cd /srv/assistente/app && docker compose up -d --build --force-recreate servidor tailscale && bash scripts/verificar.sh
      docker compose exec servidor grep -c 'Ficha 6, item 8' assistente/servidor.py
      ```
      Esperado: `ok    Paperless: http://paperless:8000 responde, token do usuário comum leonardo, nenhum documento sem dono`
      e `1` no `grep` (a imagem tem as bloqueadas da Ficha 6). O `--build` é obrigatório: o código entra na imagem, e
      sem ele o servidor sobe com a lista antiga, que deixa criar tag sem dono e ler tarefas do outro. Recrie o
      `tailscale` junto (ele usa a rede do servidor; veja o aviso do B7).
      **Funnel fora depois de recriar** (2026-10-24): o `verificar.sh` passou e, ~15 min depois, o Funnel deu `000` (o TLS
      cai na entrada pública; pela tailnet o nó dá 401 e nenhum pacote chega a ele). Recriar de novo zerou a espera: voltou
      10 min depois. Não é a rota nem o Tailnet Lock. Espere até ~20 min sem recriar nada e confira de fora:
      `curl -4 -s -o /dev/null -w '%{http_code}' https://<nome>.<tailnet>.ts.net/mcp` (esperado 401).
- [x] P4 (2026-10-24). Timers (backup às 03:45 e conferência às 07:00):
      ```bash
      cd /srv/assistente/app/paperless/deploy/systemd
      for f in paperless-*.service; do
        sed -e "s#<usuario>#$USER#g" -e "s#<app>#/srv/assistente/app#g" -e "s#<paperless_home>#/srv/paperless#g" "$f" \
          | sudo tee "/etc/systemd/system/$f" >/dev/null
      done
      sudo cp paperless-*.timer /etc/systemd/system/ && sudo systemctl daemon-reload
      sudo systemctl enable --now paperless-backup.timer paperless-conferir.timer
      sudo systemctl start paperless-backup.service && journalctl -u paperless-backup -n 5 --no-pager
      ```
      Esperado: `exportar: feito: /srv/backup-hd/paperless/paperless-AAAAMMDD-HHMM.tar.age`.
- [x] P5 (2026-10-24). Ensaio de restauração, no Mac, com a identidade do age (o i7 nunca tem a chave privada):
      ```bash
      scp i7:/srv/backup-hd/paperless/paperless-<data>.tar.age ~/Downloads/
      cd ~/Desktop/Projetos/assistente-pessoal
      bash paperless/scripts/ensaiar_restauracao.sh ~/Downloads/paperless-<data>.tar.age --chave ~/identidade-assistente.txt
      ```
      Esperado: `ensaio ok`. Ele sobe uma instalação descartável, compara documentos por dono e apaga tudo.
- [x] P6 (2026-10-24). Pelo app (Projeto "Assistente"): cole antes o texto atual da Ficha 1 (tem a linha nova do § Paperless).
      Ponha um PDF em `/srv/paperless/consumir/leonardo/` (ou suba pela interface) e peça "me mostra o último
      documento que entrou". Peça também "compartilha esse documento com a Nathalia": a resposta deve ser
      "Não consigo compartilhar: os documentos de cada um ficam separados."
- [ ] P7. Interface web, quando precisar (do Mac): `ssh -L 8010:127.0.0.1:8010 <usuario>@i7` (o usuário do i7, não o do Mac) e abra `http://127.0.0.1:8010`
      como `admin`. Para a Nathalia entrar na web, defina a senha dela ali (Usuários). Nunca dê permissão a um
      documento para o outro usuário, nem crie grupo: a conferência diária acusa (Ficha 6, decisão 3).
- [x] P8. Instância da Nathalia (PLANO 1b.1, Ficha 8; só com a ficha aprovada). ~1 h. Ensaiada no Mac em 2026-10-24
      (sem Tailscale e com segredos falsos). `COMPOSE_PROJECT_NAME=assistente-nathalia` já casa com a rede
      `assistente-nathalia-paperless` do Paperless único.
      **No i7 em 2026-10-24:** feito até o primeiro backup dela (`verificar.sh` tudo ok, Funnel 401, timer às 03:25) e
      a pasta `paperless-nathalia` com o PC Windows dela (seção 8 do `docs/SYNCTHING.md`, PDF entrou). **Em 2026-10-25:**
      ChatGPT dela conectado (Ficha 9); os testes de isolamento do fim ficaram pendentes. O Funnel dela também leva minutos para voltar depois do backup (ele religa o
      `tailscale`). Para ajustar o `.env`, `sed` com `def() { sed -i "s|^#\? \?$1=.*|$1=$2|" "$E"; }` evita erro de
      digitação; confira com os segredos mascarados (`sed -E 's/^((SENHA_|JWT_|...)[A-Z_]*=).+/\1***/'`).
      **Antes, fora do i7 (Leonardo):**
      1. Tailscale (painel): uma chave de autenticação de uso único para o nó `assistente-nathalia`. O Funnel precisa
         valer para ele na política de acesso, como para o `assistente` (B4).
      2. Google Cloud, projeto `assistente-pessoal`: cliente OAuth novo "assistente nathalia" (Aplicativo da Web), com
         origem `https://assistente-nathalia.<tailnet>.ts.net` e callback `https://assistente-nathalia.<tailnet>.ts.net/auth/callback`.
         Na tela de consentimento (em teste), a Nathalia entra como usuária de teste.
      3. O e-mail Google da Nathalia.
      **No i7.** Antes do primeiro backup dela, marque a pasta do seu: sem a marca, a instância que fizer backup
      primeiro fica com a pasta.
      ```bash
      cd /srv/assistente/app && git pull
      echo assistente > /srv/backup-hd/.instancia      # a pasta do backup é da sua instância
      sudo ASSISTENTE_HOME=/srv/assistente-nathalia bash scripts/preparar_host.sh   # árvore e timer próprios
      # esperados nesta primeira rodada: "o repositório não está em .../app" e "Timer instalado mas DESLIGADO"
      git clone https://github.com/Leonardo-Richeto/assistente-pessoal /srv/assistente-nathalia/app
      cp /srv/assistente-nathalia/app/.env.example /srv/assistente-nathalia/.env && chmod 600 /srv/assistente-nathalia/.env
      ```
      No `.env` dela (`nano /srv/assistente-nathalia/.env`): `ASSISTENTE_HOME=/srv/assistente-nathalia`,
      `COMPOSE_PROJECT_NAME=assistente-nathalia`, `COMPOSE_PROFILES=tailscale`, `NOME_USUARIO=Nathalia`, `PORTA_HOST=8001`,
      `TS_NOME=assistente-nathalia`, `TS_AUTHKEY` do item 1, `PUBLIC_BASE_URL=https://assistente-nathalia.<tailnet>.ts.net`,
      credenciais do item 2, `GOOGLE_EMAILS_PERMITIDOS=<e-mail dela>`, `VAULT_PATH=/vault`,
      `COMPOSE_FILE=docker-compose.yml:deploy/paperless/rede.yml`, `PAPERLESS_URL=http://paperless:8000`, a mesma
      `AGE_DESTINATARIO` do seu `.env` e `BACKUP_DESTINO=/srv/backup-hd/assistente-nathalia`. As senhas novas e o token
      do Paperless entram direto no arquivo, sem aparecer na tela (hex: sem `/` nem `+` na URL do banco e no `sed`):
      ```bash
      for k in SENHA_DONO SENHA_LEITURA SENHA_ESCRITA JWT_SIGNING_KEY; do
        v="$(openssl rand -hex 32)"; sed -i "s|^$k=.*|$k=$v|" /srv/assistente-nathalia/.env
      done; unset v
      cd /srv/assistente/app
      T="$(PAPERLESS_HOME=/srv/paperless bash paperless/scripts/token.sh nathalia)"
      [ -n "$T" ] && sed -i "s|^PAPERLESS_API_KEY=.*|PAPERLESS_API_KEY=$T|" /srv/assistente-nathalia/.env || echo "token.sh falhou: pare"
      unset T
      ```
      Vault inicial (perfil, onde parei e diário; git local, sem push):
      ```bash
      V=/srv/assistente-nathalia/vault; cd "$V"
      mkdir -p 00-inbox 20-areas 50-diario
      printf -- '---\ntitulo: Onde parei\ntipo: plano\n---\n\n# Onde parei\n\n## Trabalho em andamento\n\n' > 00-inbox/onde-parei.md
      printf -- '---\ntitulo: Perfil da Nathalia\ntipo: area\n---\n\n# Perfil da Nathalia\n\n' > 20-areas/perfil-do-nathalia.md
      cp /srv/assistente-nathalia/app/deploy/vault/gitignore-do-vault .gitignore
      git init -q && git add -A && git -c user.name=Leonardo -c user.email=<seu e-mail> commit -qm "Vault inicial da Nathalia"
      ```
      Subir e conferir (o Paperless de pé antes: a rede é dele):
      ```bash
      sudo ASSISTENTE_HOME=/srv/assistente-nathalia bash /srv/assistente-nathalia/app/scripts/preparar_host.sh  # liga app/.env e o timer
      cd /srv/assistente-nathalia/app && docker compose up -d --build
      bash scripts/verificar.sh             # esperado: sem FALHA, Paperless pelo token de nathalia, Funnel = 401
      systemctl list-timers 'assistente*'   # assistente-backup (03:15) e assistente-nathalia-backup (03:25)
      ```
      Se o Funnel ainda não responder, espere até ~20 min sem recriar (P3 da Fase 2.1). Depois que o nó entrar, apague
      o valor de `TS_AUTHKEY` do `.env` dela. Rode o backup dela uma vez: `sudo systemctl start assistente-nathalia-backup`
      e `ls /srv/backup-hd/assistente-nathalia`.
      **No ChatGPT da Nathalia (Ficha 9; o Claude dela fica para depois).** No i7, some os callbacks do ChatGPT ao
      `.env` dela e recrie o servidor. O `tailscale` vai junto (usa a rede do `servidor`): o Funnel pode levar até
      ~20 min para voltar; espere sem recriar.
      ```bash
      E=/srv/assistente-nathalia/.env
      sed -i 's|^#\? \?AUTH_REDIRECTS_PERMITIDOS=.*|AUTH_REDIRECTS_PERMITIDOS=https://chatgpt.com/connector_platform_oauth_redirect,https://chatgpt.com/connector/oauth/*|' "$E"
      grep '^AUTH_REDIRECTS_PERMITIDOS=' "$E"    # esperado: os dois endereços do chatgpt.com
      cd /srv/assistente-nathalia/app && docker compose up -d --force-recreate servidor tailscale
      bash scripts/verificar.sh                 # esperado: sem FALHA; Funnel = 401 (pode demorar)
      ```
      No ChatGPT dela, em chatgpt.com no PC (os nomes do menu podem variar):
      1. Configurações → Controles de dados → "Melhorar o modelo para todos" desligado (Ficha 9, regra 5).
      2. Configurações → Apps → Configurações avançadas → Modo de desenvolvedor ligado.
      3. Criar app: nome "Assistente", URL `https://assistente-nathalia.<tailnet>.ts.net/mcp`, autenticação OAuth
         (registro automático). Login Google dela. Se o ChatGPT mostrar outro endereço de callback, compare com o `.env`.
      4. Projeto "Assistente" com o "Texto para o ChatGPT" da Ficha 9. Numa conversa do Projeto, escolha o app
         "Assistente" (botão + → Modo de desenvolvedor). Se o app não aparecer no Projeto, use as instruções
         personalizadas (Ficha 9, regra 4).
      Teste: ela registra e consulta um gasto; pergunta pelo último documento (o PDF do PC dela); pergunta por
      `entrada-teste` e recebe "Não achei"; você, pelo seu app, não vê o gasto dela.
      **No Claude da Nathalia (depois):** Configurações → Conectores → conector personalizado →
      `https://assistente-nathalia.<tailnet>.ts.net/mcp` → login Google dela. Projeto "Assistente" com o texto da Ficha 1
      sem a linha da pasta de entrada (Ficha 8, item 5). Teste: ela registra e consulta um gasto; pergunta por
      `entrada-teste` e recebe "Não achei"; você, pelo seu app, não vê o gasto dela.
- [x] P9. Trocar `esposa` por `nathalia` (Leonardo, 2026-10-24), depois do commit e do push. Documentos, token e
      permissões ficam com o mesmo usuário; o script não apaga nada e pode rodar de novo. ~5 min.
      **Rode o bloco inteiro de uma vez:** depois do `git pull`, sem o `sed`, o backup das 03:45, a conferência e o
      `token.sh` param (falta `REDE_NATHALIA` no `.env`). Se `consumir/esposa` tiver arquivo, o script para antes de mudar
      qualquer coisa: espere o Paperless consumir.
      ```bash
      cd /srv/assistente/app && git pull
      sed -i 's/^USUARIOS=leonardo esposa$/USUARIOS=leonardo nathalia/; s/^REDE_ESPOSA=assistente-esposa-paperless$/REDE_NATHALIA=assistente-nathalia-paperless/' /srv/paperless/.env
      grep -E '^(USUARIOS|REDE_)' /srv/paperless/.env     # esperado: leonardo nathalia e REDE_NATHALIA
      PAPERLESS_HOME=/srv/paperless bash paperless/scripts/renomear.sh esposa nathalia
      docker network rm assistente-esposa-paperless       # a rede antiga ficou sem uso
      bash scripts/verificar.sh
      ```
      Esperado: `usuário esposa -> nathalia; workflows renomeados: 1`, `pasta: consumir/esposa -> consumir/nathalia`,
      `conferir: ok` e o `verificar.sh` sem FALHA. Ensaiado no Paperless de teste do Mac em 2026-10-24.
- [x] P10. Pasta de entrada pelo Syncthing (Ficha 7): siga a seção 8 de `docs/SYNCTHING.md`, agora no i7 e no Mac.
      iPhone e PC Windows entram depois, junto com o vault (PLANO 2.2). Teste de isolamento no i7, com o token da Nathalia direto na variável, sem aparecer na tela:
      ```bash
      # no Mac: copie um PDF chamado entrada-teste.pdf para ~/Documents/Paperless-entrada; ele some em ~1 min
      T="$(PAPERLESS_HOME=/srv/paperless bash paperless/scripts/token.sh nathalia)"
      curl -s -H "Authorization: Token $T" 'http://127.0.0.1:8010/api/documents/?title__icontains=entrada-teste' \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])'
      unset T
      ```
      Esperado: `0` (a Nathalia não vê), e pelo app "me mostra o último documento que entrou" traz o `entrada-teste`.
      Apague o documento de teste como `admin` na interface web (P7), se quiser.

### Cofre (2b.3a) — Vaultwarden no i7

Ficha 11: um Vaultwarden só do Leonardo, só pela tailnet (nó Tailscale `cofre`, HTTPS do Serve, nunca Funnel), projeto
Docker Compose próprio (`cofre/`), backup cifrado às 03:55 no HD. Ensaiado no Mac em 2026-10-27 com dados sintéticos
(`bash scripts/testes/test_cofre.sh <pasta-vazia>`: cadastro fechado e aberto, painel desligado, backup cifrado e
restauração). **Antes:** uma auth key nova da Tailscale, a senha mestra pensada e o Google Authenticator no celular.
A senha mestra não tem recuperação (sem e-mail): esquecida, o cofre só volta pelo backup com a senha antiga.

- [x] C1. (2026-10-27) Auth key do nó: no painel da Tailscale, Settings → Keys → Generate auth key, sem "Reusable" e sem
      "Ephemeral". Copie; ela vai só para o `.env` do C2.
- [x] C2. (2026-10-27) Estado e `.env`:
      ```bash
      sudo mkdir -p /srv/cofre && sudo chown "$USER": /srv/cofre && chmod 700 /srv/cofre
      cd /srv/assistente/app && git pull
      cp cofre/.env.example /srv/cofre/.env && chmod 600 /srv/cofre/.env
      sed -i "s|^COFRE_UID=.*|COFRE_UID=$(id -u)|; s|^COFRE_GID=.*|COFRE_GID=$(id -g)|; \
        s|^BACKUP_DESTINO=.*|BACKUP_DESTINO=/srv/backup-hd/cofre|; \
        s|^AGE_DESTINATARIO=.*|$(grep '^AGE_DESTINATARIO=' /srv/assistente/.env)|" /srv/cofre/.env
      nano /srv/cofre/.env   # TS_AUTHKEY (do C1) e DOMINIO=https://cofre.<tailnet>.ts.net
      ```
- [x] C3. (2026-10-27) Subir e conferir; depois, apagar a auth key do `.env` (a identidade fica em `data/tailscale`):
      ```bash
      COFRE_HOME=/srv/cofre bash cofre/scripts/preparar.sh
      sed -i 's|^TS_AUTHKEY=.*|TS_AUTHKEY=|' /srv/cofre/.env
      ```
      Esperado: `conferir: ok`, `porta: 127.0.0.1:8030 (só loopback)` e `preparar: pronto`. No Mac, com o Tailscale
      ligado, `https://cofre.<tailnet>.ts.net` abre a tela de login (o certificado pode levar ~1 min na primeira vez).
      Se o Mac não achar o endereço, ligue o Tailscale no Mac e marque "Use Tailscale DNS settings".
      No painel da Tailscale, Machines → `cofre` → "Disable key expiry", como no nó `assistente`: sem isso, o nó sai
      da tailnet em ~180 dias.
- [x] C4. (2026-10-27) Criar a conta (cadastro aberto só durante este passo):
      ```bash
      COFRE_HOME=/srv/cofre bash cofre/scripts/cadastro.sh abrir
      # no Mac: https://cofre.<tailnet>.ts.net → "Criar conta", com o seu e-mail e a senha mestra
      COFRE_HOME=/srv/cofre bash cofre/scripts/cadastro.sh fechar
      ```
      O link "Criar conta" pode não aparecer na aba já aberta (cache): use uma janela anônima ou `/#/signup`.
      Esperado no fim: `conferir: ok` e `cadastro fechado.`
- [x] C5. (2026-10-27) 2FA: no cofre, Configurações → Segurança → Login em duas etapas → Aplicativo autenticador. Escaneie no
      Google Authenticator e guarde o código de recuperação em papel, fora do Mac.
- [x] C6. (2026-10-27) Apps: no iPhone (com o Tailscale ligado), app Bitwarden → região "Auto-hospedado" → URL do cofre. No Mac,
      a extensão do Bitwarden no navegador, do mesmo jeito.
- [x] C7. (2026-10-27) Timers: backup às 03:55 e conferência às 07:05 (cadastro aberto, painel ligado ou Tailscale doente):
      ```bash
      cd /srv/assistente/app/cofre/deploy/systemd
      for f in cofre-*.service; do
        sed -e "s#<usuario>#$USER#g" -e "s#<app>#/srv/assistente/app#g" -e "s#<cofre_home>#/srv/cofre#g" "$f" \
          | sudo tee "/etc/systemd/system/$f" >/dev/null
      done
      sudo cp cofre-*.timer /etc/systemd/system/ && sudo systemctl daemon-reload
      sudo systemctl enable --now cofre-backup.timer cofre-conferir.timer
      sudo systemctl start cofre-backup.service && journalctl -u cofre-backup -n 5 --no-pager
      sudo systemctl start cofre-conferir.service && journalctl -u cofre-conferir -n 5 --no-pager
      ```
      Esperado: `exportar: feito: /srv/backup-hd/cofre/cofre-AAAAMMDD-HHMM.tar.age (... 1 contas, ...)` e `conferir: ok`.
- [x] C8. (2026-10-27) Ensaio de restauração, num Terminal do Mac (não na sessão SSH), com a identidade do age (o i7 nunca tem a chave privada):
      ```bash
      scp i7:/srv/backup-hd/cofre/cofre-<data>.tar.age ~/Downloads/
      cd ~/Desktop/Projetos/assistente-pessoal
      bash cofre/scripts/ensaiar_restauracao.sh ~/Downloads/cofre-<data>.tar.age --chave <identidade-age.txt>
      ```
      Esperado: `ensaio ok`. **Só depois deste passo** entra o primeiro segredo de verdade (critério do PLANO 2b.3a):
      as chaves do Pluggy (cópia oficial; a de uso continua no `.env`, Ficha 11, regra 8) e as senhas longas que hoje
      estão em `.env`. Apague o pacote de `~/Downloads` no fim.
