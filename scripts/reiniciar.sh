#!/usr/bin/env bash
# Reinício semanal dos programas do assistente (terça às 03:00, pelo timer assistente-reinicio).
#   scripts/reiniciar.sh
#
# Reinicia os serviços ligados, menos o Postgres (não precisa). O Tailscale usa a rede do container do
# servidor (network_mode: service:servidor): reinicia logo depois dele, senão fica preso na rede velha e o
# Funnel cai. Restart não recria o nó (a identidade fica em data/tailscale). Espera todos ficarem saudáveis.
# O backup diário não reinicia nada (scripts/exportar.sh).
source "$(dirname "$0")/lib.sh"

descobrir_home
conferir_env

SERVICOS=()
TAILSCALE=0
while IFS= read -r s; do
  case "$s" in ""|postgres) ;; tailscale) TAILSCALE=1 ;; *) SERVICOS+=("$s") ;; esac
done < <(dc ps --status running --services 2>/dev/null | tr -d '\r')
[ "${#SERVICOS[@]}" -gt 0 ] || { log "nada a reiniciar: nenhum serviço ligado além do Postgres."; exit 0; }

log "reiniciando: ${SERVICOS[*]}"
dc_quieto restart "${SERVICOS[@]}" || falha "não consegui reiniciar ${SERVICOS[*]}."
if [ "$TAILSCALE" -eq 1 ]; then
  log "reiniciando: tailscale (depois do servidor, pela rede dividida)"
  dc_quieto restart tailscale || falha "não consegui reiniciar o tailscale."
  SERVICOS+=(tailscale)
fi
for s in "${SERVICOS[@]}"; do
  esperar_saudavel "$s" 300 || falha "$s não voltou saudável depois do reinício."
done
log "feito: ${SERVICOS[*]} de pé."
