#!/usr/bin/env bash
# Imprime o token da API de um usuário comum (cria se não existe). É SEGREDO: vai direto para o
# PAPERLESS_API_KEY do .env da instância do assistente daquela pessoa, nunca para o git nem para o chat.
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/token.sh leonardo
#
# Recusa o admin e qualquer nome fora de USUARIOS: o assistente nunca usa token de superusuário.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,7p' "$0"; exit 0 ;; "") falha "falta o usuário (veja --help)." ;; esac
descobrir_home
conferir_env
gestao token GESTAO_USUARIO="$1"
