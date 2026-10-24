#!/usr/bin/env bash
# Ensaio de restauração do Paperless (PLANO 7.2 e 7.3): restaura um pacote numa instalação
# descartável, ao lado da de produção, e apaga tudo no fim. Não toca na instalação de produção.
#
#   paperless/scripts/ensaiar_restauracao.sh <pacote.tar.age> --chave <identidade-age.txt>
#   ENSAIO_PASTA=<pasta em disco> ...   # onde fica a instalação descartável (padrão: $HOME)
#
# Usa o importar.sh numa pasta temporária, com outro nome de projeto, outra porta e redes próprias.
# Prova que: o pacote abre, os documentos e os donos voltam (contagens iguais) e a Ficha 6 vale
# depois da restauração.
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
# Em disco, não em /tmp (no Debian, /tmp é RAM): a instalação descartável tem os documentos abertos.
BASE_ENSAIO="${ENSAIO_PASTA:-$HOME}"
ENSAIO="$(mktemp -d "$BASE_ENSAIO/.paperless-ensaio-XXXXXX")/paperless" || falha "não consegui criar a pasta do ensaio em $BASE_ENSAIO."
PROJETO="paperless-ensaio-$$"
mkdir -p "$ENSAIO"
limpar() {
  local codigo=$?
  # Só apaga a pasta que este script criou.
  case "$ENSAIO" in */.paperless-ensaio-??????/paperless) ;; *) exit "$codigo" ;; esac
  if [ -f "$ENSAIO/.env" ]; then
    PAPERLESS_HOME="$ENSAIO" descobrir_home
    # Só derruba o projeto do ensaio: nunca o de produção, mesmo com o .env do pacote fora do padrão.
    if [ "$(valor_env COMPOSE_PROJECT_NAME)" = "$PROJETO" ]; then
      dc down -v --remove-orphans >/dev/null 2>&1
    else
      aviso "o .env do ensaio não tem COMPOSE_PROJECT_NAME=$PROJETO; não rodei docker compose down."
    fi
  fi
  # Arquivos com dono do container (uid 1000, postgres): apagados como root num container.
  docker run --rm --user 0 --entrypoint rm -v "$(caminho_docker "$(dirname "$ENSAIO")"):/e" \
    "$(imagem_postgres)" -rf /e/paperless >/dev/null 2>&1
  rm -rf "$(dirname "$ENSAIO")"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM

# .env do ensaio: o do pacote, com pasta, projeto, porta e redes do ensaio.
log "decifrando o .env do pacote"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$ENSAIO" -xf - ./env || falha "não consegui decifrar o pacote."
PORTA=$((18000 + $$ % 1000))
sed -e "s|^[[:space:]]*PAPERLESS_HOME=.*|PAPERLESS_HOME=$(caminho_docker "$ENSAIO")|" \
    -e "s|^[[:space:]]*COMPOSE_PROJECT_NAME=.*|COMPOSE_PROJECT_NAME=$PROJETO|" \
    -e "s|^[[:space:]]*PORTA_HOST=.*|PORTA_HOST=$PORTA|" \
    -e "s|^[[:space:]]*REDE_PRINCIPAL=.*|REDE_PRINCIPAL=$PROJETO-principal|" \
    -e "s|^[[:space:]]*REDE_ESPOSA=.*|REDE_ESPOSA=$PROJETO-esposa|" \
    -e "s|^[[:space:]]*BACKUP_DESTINO=.*|BACKUP_DESTINO=|" "$ENSAIO/env" >"$ENSAIO/.env"
rm -f "$ENSAIO/env"
[ "$(valor_env COMPOSE_PROJECT_NAME "$ENSAIO/.env")" = "$PROJETO" ] \
  || falha "o .env do pacote não tem COMPOSE_PROJECT_NAME (ou não consegui trocar)."

log "restaurando em $ENSAIO (projeto $PROJETO, porta $PORTA)"
PAPERLESS_HOME="$ENSAIO" bash "$(dirname "$0")/importar.sh" "$PACOTE" --chave "$CHAVE" \
  || falha "a restauração falhou."
log "ensaio ok: o pacote abre, os documentos e os donos voltam e a Ficha 6 vale. Instalação descartável apagada."
