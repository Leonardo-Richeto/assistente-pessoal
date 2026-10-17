#!/usr/bin/env bash
# Prepara um Debian 12 limpo (VM ou bare metal) para a produção do assistente.
# Idempotente: pode rodar de novo sem estragar nada.
#   sudo bash deploy/preparar-maquina.sh --dry-run    # só imprime o que faria
#   sudo bash deploy/preparar-maquina.sh              # executa
#
# Instala: pacotes básicos, git, smartmontools, Docker Engine + compose (repositório oficial),
# Tailscale e Syncthing (repositórios oficiais), qemu-guest-agent (só em VM).
# Cria /srv/assistente e /srv/vault com dono do usuário que chamou o sudo.
#
# NÃO faz: tailscale up/funnel, .env, clone com credencial, config do Syncthing.
# Isso é do Leonardo (próximos passos impressos no fim).
set -u

DRY=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  *) echo "Uso: $0 [--dry-run]" >&2; exit 2 ;;
esac

erro() { echo "ERRO: $*" >&2; exit 1; }
info() { echo "==> $*"; }

# Executa o comando, ou só imprime com --dry-run.
run() {
  if [ "$DRY" -eq 1 ]; then
    echo "[dry-run] $*"
  else
    "$@" || erro "falhou: $*"
  fi
}

# Grava $2 (texto) em $1 só se o conteúdo mudou.
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

# Baixa uma chave GPG para o chaveiro, se ainda não existe.
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

[ -r /etc/os-release ] || erro "sem /etc/os-release; só Debian 12 é suportado."
# shellcheck disable=SC1091
. /etc/os-release
if [ "${ID:-}" != "debian" ] || [ "${VERSION_ID:-}" != "12" ]; then
  erro "este script é só para Debian 12 (bookworm). Aqui: ${PRETTY_NAME:-desconhecido}."
fi
CODENOME="bookworm"

if [ "$DRY" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || erro "rode com sudo (ou use --dry-run)."
  [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] \
    || erro "rode como usuário comum com sudo (SUDO_USER vazio ou root); /srv ficaria com dono root."
  USUARIO="$SUDO_USER"
else
  USUARIO="${SUDO_USER:-<usuario>}"
  echo "(dry-run: nada será alterado)"
fi
ARQ="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
export DEBIAN_FRONTEND=noninteractive

# --- 1. Pacotes básicos ---------------------------------------------------------------------

info "Pacotes básicos, git e smartmontools"
BASICOS=(ca-certificates curl gnupg git rsync htop tmux unzip jq openssh-server smartmontools)
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
if command -v systemd-detect-virt >/dev/null 2>&1; then
  VIRT="$(systemd-detect-virt --vm 2>/dev/null || true)"
else
  VIRT="indefinido"
fi
case "$VIRT" in
  none|"") echo "Bare metal (ou container): não instala o agente." ;;
  indefinido) echo "Não deu para detectar (systemd-detect-virt ausente): não instala o agente." ;;
  *)
    echo "VM detectada (${VIRT})."
    if dpkg -s qemu-guest-agent >/dev/null 2>&1; then
      echo "ok (já instalado)"
    else
      run apt-get install -y qemu-guest-agent
    fi
    if [ "$DRY" -eq 1 ]; then
      echo "[dry-run] systemctl enable --now qemu-guest-agent (com aviso, sem abortar, se falhar)"
    else
      systemctl enable --now qemu-guest-agent \
        || echo "aviso: o qemu-guest-agent não iniciou. No Proxmox, ligue Options > Qemu Guest Agent e faça Shutdown + Start da VM (reiniciar por dentro não basta)."
    fi
    ;;
esac

# --- 5. Pastas -------------------------------------------------------------------------------

info "Pastas /srv/assistente e /srv/vault (dono: ${USUARIO})"
GRUPO="$(id -gn "$USUARIO" 2>/dev/null || echo "$USUARIO")"
for d in /srv/assistente /srv/vault; do
  run install -d -m 0755 -o "$USUARIO" -g "$GRUPO" "$d"
done

# --- Próximos passos -------------------------------------------------------------------------

cat <<PASSOS

==> Pronto$( [ "$DRY" -eq 1 ] && echo " (dry-run: nada foi feito)").

Próximos passos, manuais (docs/IMPLANTACAO.md, Etapa B):
  1. Saia e entre de novo na sessão (grupo docker). Teste: docker compose version
  2. Se ainda não clonou: git clone https://github.com/Leonardo-Richeto/assistente-pessoal /srv/assistente
  3. sudo tailscale up            (abra o link, entre na tailnet)
     No painel do Tailscale: HTTPS, Funnel e, para esta máquina, desligar a expiração da chave (key expiry).
  4. Crie o .env em /srv/assistente (senhas novas: openssl rand -base64 48) e suba a stack.
  5. sudo tailscale funnel --bg 8000   (só depois de a stack responder)
  6. Syncthing e vault: docs/SYNCTHING.md
Fuso atual: $(timedatectl show -p Timezone --value 2>/dev/null || echo 'desconhecido'). Se não for America/Sao_Paulo:
  sudo timedatectl set-timezone America/Sao_Paulo   (o script não muda o fuso sozinho)
O script não tocou em .env, Funnel, login do Tailscale nem Syncthing.
PASSOS
