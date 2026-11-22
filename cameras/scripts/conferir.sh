#!/usr/bin/env bash
# Conferência da câmera (Ficha 18, regra 7). Sai com erro se achar: Frigate fora do ar; câmera sem imagem; última
# gravação com mais de 10 min; porta além da 8971 ou fora do loopback e do IP de casa; config.yml diferente do
# repositório; gravações acima de LIMITE_GRAVACOES_GB; disco acima de 85%.
#
#   CAMERAS_HOME=/srv/cameras cameras/scripts/conferir.sh
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,6p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac
descobrir_home
conferir_env

erros=0
problema() { echo "$NOME_SCRIPT: PROBLEMA: $*"; erros=1; }

versao="$(api version)"
[ -n "$versao" ] || problema "o Frigate não responde (docker compose logs frigate)."
fps="$(api stats | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["cameras"]["frente"]["camera_fps"])
except Exception:
    pass' 2>/dev/null)"
python3 -c "import sys; sys.exit(0 if float('${fps:-0}') > 0 else 1)" || problema "a câmera não manda imagem (camera_fps=${fps:-?}): IP, senha ou câmera desligada."
m="$(minutos_ultima_gravacao)"
[ -n "$m" ] && [ "$m" -le 10 ] || problema "última gravação com ${m:-mais de 1440} min (limite 10)."
cmp -s "$CAMERAS_APP/deploy/config.yml" "$HOME_DIR/config/config.yml" \
  || problema "config.yml do Frigate diferente do repositório (mudado pela tela?): rode o preparar.sh."
kb="$(du -sk "$HOME_DIR/gravacoes" 2>/dev/null | cut -f1)"; kb="${kb:-0}"
gb=$(( kb / 1024 / 1024 ))
limite_gb="$(valor_env LIMITE_GRAVACOES_GB)"
[ "$kb" -le $(( limite_gb * 1024 * 1024 )) ] || problema "gravações com $gb GB (teto $limite_gb GB, Ficha 18 regra 7)."
uso="$(df -P "$HOME_DIR/gravacoes" | awk 'NR==2 {gsub("%", "", $5); print $5}')"
limite="${CAMERAS_LIMITE_DISCO:-85}"  # só para teste num disco já cheio (Mac)
[ -n "$uso" ] && [ "$uso" -le "$limite" ] || problema "disco com ${uso:-?}% de uso (limite $limite%)."
linha="$(conferir_porta)" || { echo "$NOME_SCRIPT: PROBLEMA: $linha"; erros=1; }
log "frigate ${versao:-?}; câmera ${fps:-?} fps; última gravação há ${m:-?} min; gravações $gb GB; disco ${uso:-?}%; $linha"
[ "$erros" -eq 0 ] || { aviso "Ficha 18 violada (veja acima)."; exit 1; }
log "ok"
