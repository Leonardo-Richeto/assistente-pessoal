#!/usr/bin/env bash
# Prepara um Debian (12 ou 13) limpo para o assistente. Idempotente: pode rodar de novo.
#   sudo bash scripts/preparar_host.sh --dry-run    # só imprime o que faria
#   sudo bash scripts/preparar_host.sh              # executa
#
# Instala: pacotes básicos, git, python3, age, smartmontools, Docker Engine + compose, Tailscale (no host,
# só para SSH de administração pelo nome da tailnet; o Funnel do assistente é o container) e
# Syncthing (repositórios oficiais), qemu-guest-agent (só em VM).
# Cria a árvore de ASSISTENTE_HOME (padrão /srv/assistente: a pasta acima de app/):
#   app/ .env backups/ logs/ vault/ data/{postgres,paperless,tailscale,sessoes/oauth}
# Liga app/.env -> ../.env (para `docker compose` sem --env-file) e instala o timer do backup
# diário (scripts/exportar.sh --retencao), que só é ligado com AGE_DESTINATARIO no .env.
#
# NÃO faz: tailscale up, .env, chaves do age, config do Syncthing. Próximos passos no fim.
set -u

DRY=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
  *) echo "Uso: $0 [--dry-run]" >&2; exit 2 ;;
esac

erro() { echo "ERRO: $*" >&2; exit 1; }
info() { echo "==> $*"; }

run() {
  if [ "$DRY" -eq 1 ]; then
    echo "[dry-run] $*"
  else
    "$@" || erro "falhou: $*"
  fi
}

gravar_arquivo() {
  local destino="$1" conteudo="$2"
  if [ -f "$destino" ] && [ "$(cat "$destino")" = "$conteudo" ]; then
    echo "ok (já existe igual): $destino"
    return
  fi
  if [ "$DRY" -eq 1 ]; then
    echo "[dry-run] gravar $destino:"
    echo "$conteudo" | sed 's/^/[dry-run]   /'
  else
    printf '%s\n' "$conteudo" >"$destino" || erro "não gravou $destino"
  fi
}

baixar_chave() {
  local url="$1" destino="$2"
  if [ -s "$destino" ]; then
    echo "ok (chave já existe): $destino"
    return
  fi
  run curl -fsSL "$url" -o "$destino"
  run chmod a+r "$destino"
}

# --- Conferências ---------------------------------------------------------------------------

APP="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${ASSISTENTE_HOME:-/srv/assistente}"
case "$HOME_DIR" in /*) ;; *) erro "ASSISTENTE_HOME precisa ser caminho absoluto." ;; esac
HOME_DIR="${HOME_DIR%/}"

[ -r /etc/os-release ] || erro "sem /etc/os-release; só Debian 12 ou 13."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  debian:12|debian:13) CODENOME="${VERSION_CODENAME:?}" ;;
  *) erro "este script é só para Debian 12 ou 13. Aqui: ${PRETTY_NAME:-desconhecido}." ;;
esac

if [ "$DRY" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || erro "rode com sudo (ou use --dry-run)."
  [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] \
    || erro "rode como usuário comum com sudo (SUDO_USER vazio ou root); as pastas ficariam com dono root."
  USUARIO="$SUDO_USER"
else
  USUARIO="${SUDO_USER:-<usuario>}"
  echo "(dry-run: nada será alterado)"
fi
GRUPO="$(id -gn "$USUARIO" 2>/dev/null || echo "$USUARIO")"
# O container do servidor roda com uid 1000 e comita no .git do vault (PLANO 2b.4); o commit diário e o
# Syncthing rodam com este usuário. Uids diferentes travam um ao outro nas pastas de .git/objects.
if [ "$DRY" -eq 0 ] && [ "$(id -u "$USUARIO")" != "1000" ]; then
  echo "AVISO: $USUARIO tem uid $(id -u "$USUARIO"), não 1000; o commit por escrita do vault vai falhar (docs/IMPLANTACAO.md B11)." >&2
fi
ARQ="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
export DEBIAN_FRONTEND=noninteractive

# --- 1. Pacotes básicos ---------------------------------------------------------------------

info "Pacotes básicos, git, age e smartmontools"
# python3: o commit diário (resumo do relatório do gitleaks) e o lint do vault rodam no host.
BASICOS=(ca-certificates curl gnupg git rsync htop tmux unzip jq openssh-server smartmontools age python3)
FALTAM=()
for p in "${BASICOS[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || FALTAM+=("$p")
done
if [ "${#FALTAM[@]}" -gt 0 ]; then
  run apt-get update
  run apt-get install -y "${FALTAM[@]}"
else
  echo "ok (já instalados): ${BASICOS[*]}"
fi

# --- 2. Repositórios oficiais ---------------------------------------------------------------

info "Chaveiro /etc/apt/keyrings"
run install -m 0755 -d /etc/apt/keyrings

info "Repositório oficial da Docker"
baixar_chave https://download.docker.com/linux/debian/gpg /etc/apt/keyrings/docker.asc
gravar_arquivo /etc/apt/sources.list.d/docker.list \
  "deb [arch=${ARQ} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${CODENOME} stable"

info "Repositório oficial do Tailscale"
baixar_chave "https://pkgs.tailscale.com/stable/debian/${CODENOME}.noarmor.gpg" /etc/apt/keyrings/tailscale-archive-keyring.gpg
gravar_arquivo /etc/apt/sources.list.d/tailscale.list \
  "deb [signed-by=/etc/apt/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian ${CODENOME} main"

info "Repositório oficial do Syncthing"
baixar_chave https://syncthing.net/release-key.gpg /etc/apt/keyrings/syncthing-archive-keyring.gpg
gravar_arquivo /etc/apt/sources.list.d/syncthing.list \
  "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable-v2"

# --- 3. Docker, Tailscale e Syncthing --------------------------------------------------------

info "Docker Engine, compose plugin, Tailscale e Syncthing"
ALVOS=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin tailscale syncthing)
FALTAM=()
for p in "${ALVOS[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || FALTAM+=("$p")
done
if [ "${#FALTAM[@]}" -gt 0 ]; then
  run apt-get update
  run apt-get install -y "${FALTAM[@]}"
else
  echo "ok (já instalados): ${ALVOS[*]}"
fi
run systemctl enable --now docker
run systemctl enable --now tailscaled

info "Usuário ${USUARIO} no grupo docker"
if id -nG "$USUARIO" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
  echo "ok (já está no grupo docker)"
else
  run usermod -aG docker "$USUARIO"
  echo "Aviso: saia e entre de novo na sessão para o grupo valer."
fi

# --- 4. qemu-guest-agent só em VM -----------------------------------------------------------

info "qemu-guest-agent (só em VM)"
VIRT="$(systemd-detect-virt --vm 2>/dev/null || true)"
case "$VIRT" in
  none|"") echo "Bare metal (ou indefinido): não instala o agente." ;;
  *)
    echo "VM detectada (${VIRT})."
    dpkg -s qemu-guest-agent >/dev/null 2>&1 && echo "ok (já instalado)" || run apt-get install -y qemu-guest-agent
    if [ "$DRY" -eq 1 ]; then
      echo "[dry-run] systemctl enable --now qemu-guest-agent"
    else
      systemctl enable --now qemu-guest-agent || echo "aviso: o qemu-guest-agent não iniciou (ligue o agente nas opções da VM)."
    fi
    ;;
esac

# --- 5. Árvore de ASSISTENTE_HOME ------------------------------------------------------------

info "Pastas de ${HOME_DIR} (dono: ${USUARIO})"
for d in "$HOME_DIR" "$HOME_DIR/backups" "$HOME_DIR/logs" "$HOME_DIR/vault" "$HOME_DIR/data" \
         "$HOME_DIR/data/paperless" "$HOME_DIR/data/sessoes" "$HOME_DIR/data/vault-versoes"; do
  run install -d -m 0750 -o "$USUARIO" -g "$GRUPO" "$d"
done
# O Postgres e o Tailscale cuidam dos donos das próprias pastas; o servidor roda com uid 1000.
run install -d -m 0700 -o root -g root "$HOME_DIR/data/postgres"
run install -d -m 0700 -o root -g root "$HOME_DIR/data/tailscale"
run install -d -m 0700 -o 1000 -g 1000 "$HOME_DIR/data/sessoes/oauth"

if [ "$APP" = "$HOME_DIR/app" ]; then
  if [ -L "$APP/.env" ]; then
    echo "ok (link já existe): $APP/.env"
  elif [ -e "$APP/.env" ]; then
    echo "aviso: $APP/.env é um arquivo comum. Mova-o para $HOME_DIR/.env e rode de novo."
  else
    run ln -s ../.env "$APP/.env"
  fi
else
  echo "aviso: o repositório não está em $HOME_DIR/app (está em $APP). Clone em $HOME_DIR/app."
fi

# --- 6. Backup diário ------------------------------------------------------------------------

# Uma unidade por instância, com o nome da pasta: /srv/assistente -> assistente-backup (a de sempre),
# /srv/assistente-nathalia -> assistente-nathalia-backup. Nome fixo faria a segunda instância tomar o backup da primeira.
UNIDADE="$(basename "$HOME_DIR")-backup"
info "Timer do backup diário ${UNIDADE} (03:15, scripts/exportar.sh --retencao)"
UNIDADE_SRV="$(sed -e "s#<usuario>#${USUARIO}#g" -e "s#<home>#${HOME_DIR}#g" "$APP/deploy/systemd/assistente-backup.service")"
gravar_arquivo "/etc/systemd/system/${UNIDADE}.service" "$UNIDADE_SRV"
gravar_arquivo "/etc/systemd/system/${UNIDADE}.timer" "$(cat "$APP/deploy/systemd/assistente-backup.timer")"
run systemctl daemon-reload
if [ -f "$HOME_DIR/.env" ] && grep -Eq '^AGE_DESTINATARIO=age1' "$HOME_DIR/.env"; then
  run systemctl enable --now "${UNIDADE}.timer"
else
  echo "Timer instalado mas DESLIGADO: falta AGE_DESTINATARIO no $HOME_DIR/.env. Depois de preencher, rode este script de novo."
fi

# --- Próximos passos -------------------------------------------------------------------------

cat <<PASSOS

==> Pronto$( [ "$DRY" -eq 1 ] && echo " (dry-run: nada foi feito)").

Próximos passos (docs/MIGRACAO.md e docs/IMPLANTACAO.md):
  1. Saia e entre de novo na sessão (grupo docker). Teste: docker compose version
  2. sudo tailscale up --hostname=<nome-do-host>   (nó do HOST, só para SSH; o do assistente é o container)
  3. Máquina nova vazia: cp $HOME_DIR/app/.env.example $HOME_DIR/.env, preencha e suba:
       cd $HOME_DIR/app && docker compose up -d --build
     Migração: scripts/importar.sh <pacote.tar.age> --chave <identidade-age.txt>
  4. Syncthing e vault: docs/SYNCTHING.md (pasta $HOME_DIR/vault)
Fuso atual: $(timedatectl show -p Timezone --value 2>/dev/null || echo 'desconhecido'). Se não for America/Sao_Paulo:
  sudo timedatectl set-timezone America/Sao_Paulo
PASSOS
