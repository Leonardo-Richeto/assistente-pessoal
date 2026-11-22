#!/usr/bin/env bash
# Sobe o Immich (Ficha 17) sem o ML e confere. Idempotente: rode de novo depois de trocar a versão.
#
#   FOTOS_HOME=/srv/fotos fotos/scripts/preparar.sh
#
# Primeira vez: sobe só no loopback. Crie o administrador (o Leonardo) por um túnel SSH até a porta do .env e rode
# de novo: aí a porta da rede de casa liga. Assim ninguém do Wi-Fi vira administrador antes dele.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,7p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac

descobrir_home
conferir_env
criar_pastas
log "subindo o Immich sem o ML, só no loopback (primeira vez: baixa ~2 GB de imagens)"
FOTOS_SO_LOOPBACK=1 dc_quieto up -d database redis immich-server || falha "docker compose up falhou."
FOTOS_SO_LOOPBACK=1 esperar_saudavel immich-server 300 || falha "o Immich não ficou saudável (docker compose logs immich-server)."

estado="$(inicializado)"
[ -n "$estado" ] || falha "o Immich não respondeu em $(base_local)/api/server/config."
if [ "$estado" != sim ]; then
  log "sem administrador ainda: a porta da rede de casa fica desligada."
  log "crie a conta do Leonardo em $(base_local) (no i7: ssh -o ExitOnForwardFailure=yes -L 18040:127.0.0.1:$(porta_host) <i7> e abra http://127.0.0.1:18040) e rode este script de novo."
  exit 0
fi

if com_lan; then
  log "ligando a porta da rede de casa ($(valor_env ENDERECO_LAN):$(valor_env PORTA_LAN))"
  dc_quieto up -d immich-server || falha "não consegui ligar a porta da rede de casa."
  esperar_saudavel immich-server 300 || falha "o Immich não ficou saudável depois de ligar a rede de casa."
fi
bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
log "pronto.$(com_lan && echo " No app do iPhone: http://$(valor_env ENDERECO_LAN):$(valor_env PORTA_LAN)")"
