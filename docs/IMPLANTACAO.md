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
serviços dele vierem para o i7 (`PLANO.md` Fase 1c). Sem backup do banco por enquanto (`PLANO.md` Fase 7). Troque `<usuario>` pelo seu usuário Linux e
`<maquina>.<tailnet>.ts.net` pelo endereço real (nunca grave o real no repo, que é público).
Scripts: `deploy/inventario.sh`, `deploy/preparar-maquina.sh`, `deploy/backup-banco.sh`,
`deploy/restaurar-banco.sh`, `deploy/vault/`. Vault e Syncthing: `docs/SYNCTHING.md`.

### Roteiro da implantação

Tempo total estimado: 3h a 4h. Marque conforme avança. A numeração dos passos B segue o `SPRINT.md`;
a **ordem de execução** é a desta lista (B10 vem antes de B8 de propósito: o conector novo só entra
depois de os dados estarem no lugar).

0. [x] Pré-condição, cumprida pelo orquestrador: os scripts estão no GitHub (commit e push feitos antes).
   Confira: `git ls-remote https://github.com/Leonardo-Richeto/assistente-pessoal main` e
   `curl -fsI https://raw.githubusercontent.com/Leonardo-Richeto/assistente-pessoal/main/deploy/inventario.sh`
   (deve responder `200`). Se der 404, pare: o push não aconteceu.
1. [ ] (5 min) Ligue o i7 na tomada medidora. A máquina está decidida: i7 com Debian direto (2026-10-18).
2. [ ] (10 min) Inventário no host (B1). No i7, **antes** de apagar o sistema atual.
3. [ ] (40 a 60 min) BIOS, Debian 12 no i7 e economia de energia (B2).
4. [ ] (10 min) Na máquina nova: clonar o repo e rodar `sudo bash deploy/preparar-maquina.sh` (B3).
5. [ ] (10 min) `sudo tailscale up`, HTTPS e Funnel no painel, key expiry desligada (B4).
6. [ ] (10 min) Google Cloud Console: acrescentar a URL nova ao cliente OAuth (B5).
7. [ ] (15 min) `.env` com senhas novas, subir a stack, `sudo tailscale funnel --bg 8000`, 401 sem token (B6, B7).
8. [ ] (2 min) No Mac: `docker compose stop servidor`. O Postgres do Mac fica de pé e nada novo é gravado (B7b).
9. [ ] (30 min) Dados do Mac: backup, `scp`, restaurar em banco novo, conferir, decidir e trocar (B10).
10. [ ] (15 min) claude.ai: conector novo, trocar no Projeto "Assistente" (B8) e testes do A10 (B9).
11. [ ] (5 min) Só agora, no Mac: `tailscale funnel --https=443 off` e `docker compose stop` (B9b).
12. [ ] (40 min) Vault e Syncthing e o timer do commit do vault (B11, `docs/SYNCTHING.md`).
13. [ ] (5 min) Anote o consumo parado (lido no B2c) e comece os 7 dias de medição com a stack (`PLANO.md` 1.7).

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
      sudo git clone https://github.com/Leonardo-Richeto/assistente-pessoal /srv/assistente
      sudo chown -R "$USER": /srv/assistente
      sudo bash /srv/assistente/deploy/preparar-maquina.sh --dry-run    # leia a saída
      sudo bash /srv/assistente/deploy/preparar-maquina.sh
      ```
      O clone é por HTTPS: o repositório é público, sem credencial. O script recusa se não for Debian 12,
      é idempotente, instala Docker + compose, Tailscale, Syncthing, smartmontools e (só em VM) qemu-guest-agent.
      Não roda `tailscale up`, não mexe no `.env`. Saia e entre de novo na sessão (grupo `docker`).
      Se `/srv/assistente` já existir vazia (criada pelo script), clone com `git clone <url> .` dentro dela.
      Confira: `docker compose version` e o fuso: `timedatectl`. Se não for `America/Sao_Paulo`:
      `sudo timedatectl set-timezone America/Sao_Paulo` (o script só imprime; não muda sozinho).
- [ ] B4. Tailscale: `sudo tailscale up` (abra o link no navegador e entre na tailnet).
      Nome da máquina: um nome neutro (opção `--hostname=<nome>`) mantém a URL se a máquina for trocada um dia,
      desde que remova a máquina antiga no painel. No painel do Tailscale: HTTPS e Funnel para a máquina.
      No painel, desligue o **key expiry** desta máquina (senão ela cai da tailnet em meses).
      Depois que a stack responder (B7): `sudo tailscale funnel --bg 8000` (no Linux o Funnel pede sudo) e anote
      `https://<maquina>.<tailnet>.ts.net`.
- [ ] B5. Login. No Google Cloud Console, no cliente OAuth do projeto `assistente-pessoal` (como no Passo 4 da
      Sprint 1), **acrescente** a URL nova: em "Origens JavaScript autorizadas" a
      `https://<maquina>.<tailnet>.ts.net` e em "URIs de redirecionamento autorizados" a
      `https://<maquina>.<tailnet>.ts.net/auth/callback`. Não remova as do Mac até a troca terminar.
      A mudança pode levar alguns minutos para valer. Se preferir um cliente de produção separado, crie outro
      e use as credenciais dele. O **desligamento do Mac** é o último passo (B9b), não este.
- [ ] B6. `.env` novo em `/srv/assistente` (`cp .env.example .env`; o `.env` nunca vai para o git):
      - Senhas novas e diferentes: `SENHA_DONO`, `SENHA_LEITURA`, `SENHA_ESCRITA` e `JWT_SIGNING_KEY`.
        Gere uma por vez: `openssl rand -base64 48`. **Nunca reaproveite as do Mac.**
      - `PUBLIC_BASE_URL=https://<maquina>.<tailnet>.ts.net`, `AUTH_PROVEDOR=google`, credenciais do Google,
        `GOOGLE_EMAILS_PERMITIDOS=<seu e-mail>`. Sem `AUTH_DESATIVADA`.
      - `VAULT_PATH` vazio por enquanto (entra no B11).
      Proteja o arquivo: `chmod 600 .env`.
- [ ] B7. Subir: `cd /srv/assistente && docker compose up -d --build` e `docker compose logs -f servidor`.
      Depois `sudo tailscale funnel --bg 8000`. Confira:
      ```bash
      docker compose ps                                                 # tudo saudável; migracao terminou
      curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/mcp    # 401 (sem token)
      curl -s -o /dev/null -w '%{http_code}\n' https://<maquina>.<tailnet>.ts.net/mcp   # 401
      curl -s https://<maquina>.<tailnet>.ts.net/.well-known/oauth-protected-resource/mcp   # responde
      ```
      Se o `/mcp` responder 200 sem token: **pare**, desligue o Funnel (`sudo tailscale funnel --https=443 off`) e investigue.
- [ ] B7b. No Mac, pare só o servidor: `cd ~/Desktop/Projetos/assistente-pessoal && docker compose stop servidor`.
      O Postgres do Mac continua de pé (o backup do B10 precisa dele) e nada novo é gravado.
- [ ] B10. Decidir se os registros do Mac vão para a produção ou se começa limpo. Para levar:
      1. No Mac, na pasta do projeto (o Postgres de pé, o servidor parado pelo B7b):
         `BACKUP_DIR=~/backup-mac bash deploy/backup-banco.sh`
      2. Copie: `scp ~/backup-mac/assistente-<data>.dump <usuario>@<maquina>:/tmp/`
      3. Na produção, restaure num banco **novo** (o script recusa o nome `assistente`):
         `bash /srv/assistente/deploy/restaurar-banco.sh /tmp/assistente-<data>.dump assistente_mac`
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
- [ ] B8. No claude.ai: Configurações → Conectores → adicionar conector personalizado `https://<maquina>.<tailnet>.ts.net/mcp`
      e entrar com o Google. No Projeto "Assistente": trocar o conector do Mac pelo novo. Depois remova o conector
      de teste.
- [ ] B9. Repetir os testes do A10 pelo iPhone (gasto → consultar → desfazer; ponto → horas).
- [ ] B9b. Só depois de B8 e B9 funcionarem, desligue o Mac:
      ```bash
      tailscale funnel --https=443 off                                  # no Mac (sudo, se pedir)
      cd ~/Desktop/Projetos/assistente-pessoal && docker compose stop   # sem -v, os dados do Mac ficam
      ```
- [ ] B11. Vault e Syncthing: siga `docs/SYNCTHING.md` (Syncthing como serviço, pasta `/srv/vault`, aparelhos,
      versionamento Staggered com as versões em `/srv/vault-versoes`, `.gitignore` do vault, timer do commit às
      03:30, `VAULT_PATH=/srv/vault` no `.env`). **Não verificado:** se o Synctrain aceita padrões de ignorar, e se o
      Obsidian do iPhone abre a pasta do Synctrain.
- [ ] B12. **Adiado** (Leonardo, 2026-10-18): sem backup do banco por enquanto (`PLANO.md` Fase 7). O roteiro do
      timer com o `deploy/backup-banco.sh` está no histórico do git (commit `73b0c87`, este arquivo).
- [ ] B13. Seguir para a Fase 2 do `PLANO.md` (Paperless).
