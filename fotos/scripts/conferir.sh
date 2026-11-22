#!/usr/bin/env bash
# Conferência das fotos (Ficha 17, regra 8). Sai com erro se achar: Immich fora do ar; sem administrador; porta
# fora do loopback e do IP da rede de casa; Immich na interface do Tailscale ou no Funnel; ML ligado fora da janela;
# perfil ml no .env; disco da biblioteca acima de 85%. A idade do último backup entra com o backup (PLANO 10.4).
#
#   FOTOS_HOME=/srv/fotos fotos/scripts/conferir.sh
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,6p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac
descobrir_home
conferir_env

erros=0
problema() { echo "$NOME_SCRIPT: PROBLEMA: $*"; erros=1; }
base="$(base_local)"

responde "$base" || problema "o Immich não responde em $base/api/server/ping."
[ "$(inicializado)" = sim ] || problema "o Immich não tem administrador: o primeiro a abrir a página vira administrador."
# Ficha 17, regra 2: sem nó Tailscale nem Funnel para as fotos.
[ ! -e "$FOTOS_APP/deploy/serve.json" ] || problema "fotos/deploy/serve.json existe: as fotos ficam só na rede de casa."
dc config --services 2>/dev/null | tr -d '\r' | grep -qx tailscale && problema "serviço tailscale no compose das fotos (Ficha 17, regra 2)."
# A janela semanal (PLANO 10.3) liga o ML com FOTOS_JANELA_ML=1; fora dela, ML ligado é problema.
if [ "${FOTOS_JANELA_ML:-0}" != 1 ] && ml_rodando; then
  problema "o ML está ligado fora da janela semanal (Ficha 17, regra 6): docker compose -p $(valor_env COMPOSE_PROJECT_NAME) stop immich-machine-learning."
fi
uso="$(df -P "$HOME_DIR/data/biblioteca" | awk 'NR==2 {gsub("%", "", $5); print $5}')"
# FOTOS_LIMITE_DISCO só para teste num disco já cheio (Mac); na produção vale o 85% da Ficha 17.
limite="${FOTOS_LIMITE_DISCO:-85}"
[ -n "$uso" ] && [ "$uso" -le "$limite" ] || problema "disco da biblioteca com ${uso:-?}% de uso (limite $limite%)."
linha="$(conferir_porta)" || erros=1
log "$linha; disco: ${uso:-?}%"
[ "$erros" -eq 0 ] || { aviso "Ficha 17 violada (veja acima)."; exit 1; }
log "ok"
