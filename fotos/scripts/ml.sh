#!/usr/bin/env bash
# ML do Immich fora do tempo todo (Ficha 17, regra 6; PLANO 10.3).
#
#   FOTOS_HOME=/srv/fotos fotos/scripts/ml.sh janela    # timer fotos-ml: domingo 00:30, até esvaziar ou 150 min
#   FOTOS_HOME=/srv/fotos fotos/scripts/ml.sh estado    # filas do ML agora
#   FOTOS_HOME=/srv/fotos fotos/scripts/ml.sh desligar  # para o ML na hora
#
# Importação inicial (exceção da regra 6): a mesma janela, mais longa, fora da sessão SSH:
#   sudo systemd-run --unit fotos-ml-importacao -p User=$USER -E FOTOS_HOME=/srv/fotos -E FOTOS_ML_MINUTOS=1440 \
#     /bin/bash /srv/assistente/app/fotos/scripts/ml.sh janela
#
# Janela: liga o ML, limpa as falhas da semana (com o ML parado, cada foto nova falha nas filas do ML; o "start"
# abaixo pega de novo tudo o que ainda não foi processado), põe na fila só o que falta, espera esvaziar e desliga.
# Duplicatas e rostos vêm depois da busca e da detecção, porque dependem delas. Uma segunda passada pega o que
# falhou (ex.: o modelo ainda baixando na primeira rodada). Desliga o ML sempre, mesmo com erro.
# Precisa de IMMICH_API_KEY no .env: chave do administrador com as permissões job.create e queue.read.
source "$(dirname "$0")/comum.sh"

MODO="${1:-}"
case "$MODO" in
  -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
  janela|desligar|estado) ;;
  *) falha "uso: ml.sh janela|estado|desligar" ;;
esac

descobrir_home
conferir_env
# O perfil do ML só neste script (o .env nunca tem "ml", Ficha 17, regra 6).
export COMPOSE_PROFILES=ml

FILAS_PRIMEIRO=(smartSearch faceDetection ocr)
FILAS_DEPOIS=(duplicateDetection facialRecognition)
FILAS_ML=("${FILAS_PRIMEIRO[@]}" "${FILAS_DEPOIS[@]}")

CHAVE="$(valor_env IMMICH_API_KEY)"
[ "$MODO" = desligar ] || [ -n "$CHAVE" ] \
  || falha "sem IMMICH_API_KEY no $ENV_FILE (chave do administrador, permissões job.create e queue.read)."

api() {  # <método> <caminho> [corpo json]
  local saida codigo args=(-s -m 30 -w '\n%{http_code}' -X "$1" -H "x-api-key: $CHAVE" -H 'Content-Type: application/json')
  [ -z "${3:-}" ] || args+=(-d "$3")
  saida="$(curl "${args[@]}" "$(base_local)/api$2")" || { aviso "API $1 $2 sem resposta."; return 1; }
  codigo="${saida##*$'\n'}"
  case "$codigo" in
    2??) printf '%s' "${saida%$'\n'*}" ;;
    *) aviso "API $1 $2 respondeu $codigo: ${saida%$'\n'*}"; return 1 ;;
  esac
}

comando_fila() { api PUT "/jobs/$1" "{\"command\": \"$2\", \"force\": false}" >/dev/null || falha "não consegui '$2' na fila $1."; }
comando_filas() { local c="$1" f; shift; for f in "$@"; do comando_fila "$f" "$c"; done; }

# "pendentes falhas" das filas pedidas, somadas: <fila>...
contar_filas() {
  local filas
  filas="$(api GET /queues)" || return 1
  printf '%s' "$filas" | python3 -I -c '
import json, sys
filas = set(sys.argv[1:])
pend = falhas = 0
for f in json.load(sys.stdin):
    if f["name"] in filas:
        e = f["statistics"]
        pend += e["active"] + e["waiting"] + e["delayed"]
        falhas += e["failed"]
print(pend, falhas)' "$@"
}

esperar_filas() {  # <limite em epoch> <fila>...
  local limite="$1" pend falhas; shift
  sleep 5  # o "start" põe as tarefas na fila aos poucos
  while :; do
    read -r pend falhas < <(contar_filas "$@") || { aviso "não consegui ler as filas."; return 1; }
    [ "$pend" -eq 0 ] && return 0
    [ "$(date +%s)" -lt "$limite" ] || { aviso "a janela acabou com $pend tarefas na fila ($*); seguem no domingo seguinte."; return 1; }
    sleep 30
  done
}

desligar_ml() {
  dc_quieto stop immich-machine-learning || { aviso "não consegui parar o ML."; return 1; }
  log "ML desligado"
}

estado() {
  local pend falhas
  read -r pend falhas < <(contar_filas "${FILAS_ML[@]}") || falha "não consegui ler as filas."
  log "filas do ML: $pend pendentes, $falhas com falha; ML $(ml_rodando && echo ligado || echo parado)"
}

case "$MODO" in
  estado) estado; exit 0 ;;
  desligar) desligar_ml; janela_em_andamento || rm -f "$MARCA_JANELA"; exit 0 ;;
esac

# janela
limite=$(( $(date +%s) + ${FOTOS_ML_MINUTOS:-150} * 60 ))
echo "$$" > "$MARCA_JANELA"
trap 'desligar_ml; rm -f "$MARCA_JANELA"' EXIT
log "ligando o ML (primeira vez: baixa a imagem e os modelos, ~2 GB)"
dc_quieto up -d immich-machine-learning || falha "não consegui subir o ML."
esperar_saudavel immich-machine-learning 600 || falha "o ML não ficou saudável (docker compose logs immich-machine-learning)."
comando_filas clear-failed "${FILAS_ML[@]}"
completo=1
for passada in 1 2; do
  comando_filas start "${FILAS_PRIMEIRO[@]}"
  esperar_filas "$limite" "${FILAS_PRIMEIRO[@]}" || { completo=0; break; }
  comando_filas start "${FILAS_DEPOIS[@]}"
  esperar_filas "$limite" "${FILAS_DEPOIS[@]}" || { completo=0; break; }
  read -r _ falhas < <(contar_filas "${FILAS_ML[@]}") || { aviso "não consegui ler as filas."; completo=0; break; }
  [ "$falhas" -eq 0 ] && break
  [ "$passada" -eq 2 ] && { aviso "$falhas falhas depois da 2ª passada; ficam para o domingo seguinte."; completo=0; }
  if [ "$passada" -eq 1 ]; then
    log "$falhas falhas na 1ª passada; limpando e tentando de novo"
    comando_filas clear-failed "${FILAS_ML[@]}"
  fi
done
estado
if [ "$completo" -eq 1 ]; then log "janela feita"; else log "janela parcial (veja o aviso acima)"; fi
