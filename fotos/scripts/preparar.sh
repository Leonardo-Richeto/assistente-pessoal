#!/usr/bin/env bash
# Sobe o Immich (Ficha 17) sem o ML e confere. Idempotente: rode de novo depois de trocar a versão.
#
#   FOTOS_HOME=/srv/fotos fotos/scripts/preparar.sh
#
# Primeira vez: sobe só no loopback. Crie o administrador (o Leonardo) por um túnel SSH até a porta do .env e rode
# de novo: aí o Tailscale sobe. Assim ninguém da tailnet vira administrador antes dele.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,7p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac

descobrir_home
conferir_env
criar_pastas
log "subindo o Immich sem o ML (primeira vez: baixa ~2 GB de imagens)"
dc_quieto up -d database redis immich-server || falha "docker compose up falhou."
esperar_saudavel immich-server 300 || falha "o Immich não ficou saudável (docker compose logs immich-server)."

estado="$(inicializado)"
[ -n "$estado" ] || falha "o Immich não respondeu em $(base_local)/api/server/config."
if [ "$estado" != sim ]; then
  log "sem administrador ainda: o Tailscale fica desligado."
  log "crie a conta do Leonardo em $(base_local) (no i7: ssh -L $(porta_host):127.0.0.1:$(porta_host) <i7>) e rode este script de novo."
  exit 0
fi

if perfil_tailscale; then
  # O Tailscale divide a rede do server: recriado o server, o Tailscale é recriado junto (senão fica sem rede).
  dc_quieto up -d --force-recreate --no-deps tailscale || falha "não consegui subir o Tailscale."
  esperar_saudavel tailscale 180 || falha "o Tailscale não ficou saudável (docker compose logs tailscale)."
fi
bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
log "pronto."
