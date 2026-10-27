#!/usr/bin/env bash
# Ensaio de restauração do cofre (Ficha 11, regra 7): restaura um pacote numa instalação descartável, sem o
# Tailscale, ao lado da de produção, e apaga tudo no fim. Não toca na instalação de produção.
#
#   cofre/scripts/ensaiar_restauracao.sh <pacote.tar.age> --chave <identidade-age.txt>
#   ENSAIO_PASTA=<pasta em disco> ...   # onde fica a instalação descartável (padrão: $HOME)
#
# Prova que: o pacote abre, o banco e as chaves voltam (contagens iguais), o Vaultwarden sobe com eles e a Ficha 11
# vale depois da restauração.
source "$(dirname "$0")/comum.sh"

PACOTE="" CHAVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    -*) falha "opção desconhecida: $1 (veja --help)" ;;
    *) PACOTE="$1"; shift ;;
  esac
done
[ -n "$PACOTE" ] || falha "falta o pacote (veja --help)."
[ -n "$CHAVE" ] || falha "falta --chave <identidade-age.txt>."
PACOTE="$(absoluto "$PACOTE")"; CHAVE="$(absoluto "$CHAVE")"
[ -f "$PACOTE" ] && [ -f "$CHAVE" ] || falha "pacote ou identidade não encontrados."

umask 077
BASE_ENSAIO="${ENSAIO_PASTA:-$HOME}"
ENSAIO="$(mktemp -d "$BASE_ENSAIO/.cofre-ensaio-XXXXXX")/cofre" || falha "não consegui criar a pasta do ensaio em $BASE_ENSAIO."
PROJETO="ensaio-cofre-restauracao-$$"
mkdir -p "$ENSAIO"
limpar() {
  local codigo=$?
  # Só apaga a pasta que este script criou.
  case "$ENSAIO" in */.cofre-ensaio-??????/cofre) ;; *) exit "$codigo" ;; esac
  if [ -f "$ENSAIO/.env" ]; then
    COFRE_HOME="$ENSAIO" descobrir_home
    # Só derruba o projeto do ensaio: nunca o de produção.
    if [ "$(valor_env COMPOSE_PROJECT_NAME)" = "$PROJETO" ]; then
      dc down -v --remove-orphans >/dev/null 2>&1
    else
      aviso "o .env do ensaio não tem COMPOSE_PROJECT_NAME=$PROJETO; não rodei docker compose down."
    fi
  fi
  rm -rf "$(dirname "$ENSAIO")"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM

# .env do ensaio: o do pacote, com pasta, projeto e porta do ensaio, sem Tailscale e com o dono local dos arquivos.
log "decifrando o .env do pacote"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$ENSAIO" -xf - ./env || falha "não consegui decifrar o pacote."
PORTA=$((18500 + $$ % 400))
sed -e "s|^[[:space:]]*COFRE_HOME=.*|COFRE_HOME=$(caminho_docker "$ENSAIO")|" \
    -e "s|^[[:space:]]*COMPOSE_PROJECT_NAME=.*|COMPOSE_PROJECT_NAME=$PROJETO|" \
    -e "s|^[[:space:]]*PORTA_HOST=.*|PORTA_HOST=$PORTA|" \
    -e "s|^[[:space:]]*COMPOSE_PROFILES=.*|COMPOSE_PROFILES=|" \
    -e "s|^[[:space:]]*TS_AUTHKEY=.*|TS_AUTHKEY=|" \
    -e "s|^[[:space:]]*COFRE_UID=.*|COFRE_UID=$(id -u)|" \
    -e "s|^[[:space:]]*COFRE_GID=.*|COFRE_GID=$(id -g)|" \
    -e "s|^[[:space:]]*BACKUP_DESTINO=.*|BACKUP_DESTINO=|" "$ENSAIO/env" >"$ENSAIO/.env"
rm -f "$ENSAIO/env"
[ "$(valor_env COMPOSE_PROJECT_NAME "$ENSAIO/.env")" = "$PROJETO" ] \
  || falha "o .env do pacote não tem COMPOSE_PROJECT_NAME (ou não consegui trocar)."

log "restaurando em $ENSAIO (projeto $PROJETO, porta $PORTA)"
COFRE_HOME="$ENSAIO" bash "$(dirname "$0")/importar.sh" "$PACOTE" --chave "$CHAVE" || falha "a restauração falhou."
log "ensaio ok: o pacote abre, o banco e as chaves voltam e a Ficha 11 vale. Instalação descartável apagada."
