#!/usr/bin/env bash
# Conferência diária da Ficha 6 (timer paperless-conferir). Sai com erro se achar:
#   documento sem dono (visível aos dois) ou com permissão dada a outro usuário ou grupo;
#   grupo com membros; tag, correspondente, tipo ou caminho sem dono;
#   superusuário além do admin; usuário comum com permissão diferente da ficha, staff ou em grupo;
#   workflow de dono ausente; interface web fora do 127.0.0.1.
# Avisa, sem sair com erro, arquivo parado há mais de 24 h na pasta de entrada (Ficha 7).
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/conferir.sh
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,9p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac
descobrir_home
conferir_env

erros=0
# PARADO_HORAS (padrão 24): idade do arquivo esquecido na pasta de entrada que vira aviso (Ficha 7).
saida="$(gestao conferir ${PARADO_HORAS:+PARADO_HORAS="$PARADO_HORAS"})" || { aviso "a conferência não rodou (o webserver está de pé?)."; exit 1; }
printf '%s\n' "$saida" | sed "s/^/$NOME_SCRIPT: /"
[ "$(printf '%s\n' "$saida" | tail -n 1)" = ok ] || erros=1
linha="$(conferir_porta)" || erros=1
log "$linha"
[ "$erros" -eq 0 ] || { aviso "Ficha 6 violada: corrija pela interface web (como admin) e rode de novo."; exit 1; }
log "ok"
