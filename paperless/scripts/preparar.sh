#!/usr/bin/env bash
# Sobe o Paperless único e acerta usuários, permissões e workflows de dono (Ficha 6). Idempotente:
# rode de novo depois de trocar a versão ou a lista USUARIOS.
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/preparar.sh
#
# 1. cria as pastas do estado (data/, consumir/<pessoa>, export/, backups/);
# 2. docker compose up -d e espera o webserver ficar saudável;
# 3. cria ou acerta os usuários comuns (sem superusuário, sem staff, permissões do item 2) e os
#    workflows "dono: ..." (raiz de consumir/ vai para o primeiro de USUARIOS);
# 4. roda a conferência (conferir.sh) e para com erro se ela achar problema.
# Não cria token: para isso, paperless/scripts/token.sh <pessoa>.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,13p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac

descobrir_home
conferir_env
criar_pastas

log "subindo (primeira vez: baixa as imagens e o idioma por; pode levar alguns minutos)"
dc_quieto up -d || falha "docker compose up falhou."
esperar_saudavel webserver 600 || falha "o webserver não ficou saudável (docker compose logs webserver)."

log "usuários e workflows"
gestao preparar || falha "a preparação falhou."

bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
log "pronto. Interface web: http://127.0.0.1:$(valor_env PORTA_HOST) (no i7, por túnel SSH)."
