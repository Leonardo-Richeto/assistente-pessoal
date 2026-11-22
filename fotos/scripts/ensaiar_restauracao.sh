#!/usr/bin/env bash
# Ensaio de restauração das fotos (Ficha 17, regras 7 e 9b). Roda no Mac, com a identidade do age (o i7 nunca tem
# a chave privada), sobre uma cópia da pasta do backup. Não toca no i7 e apaga tudo no fim.
#
#   rsync -a <i7>:/srv/backup-hd/fotos/ ~/fotos-ensaio/          # cópia do backup (no Mac)
#   fotos/scripts/ensaiar_restauracao.sh ~/fotos-ensaio --chave <identidade-age.txt>
#   ... --amostra 200                                           # decifra só 200 originais sorteados
#   ENSAIO_PASTA=<pasta em disco> ...                           # onde decifrar (padrão: $HOME)
#
# Prova que: o pacote mais novo abre e confere (SHA256SUMS); o dump do banco volta num Postgres descartável do
# Immich, sem erro do psql, com usuários, fotos e álbuns; cada foto do banco e cada original do índice tem o .age no
# backup; os originais decifrados têm o tamanho do índice. Não prova o conteúdo byte a byte (o age já confere a
# integridade de cada .age ao decifrar).
source "$(dirname "$0")/../../scripts/lib.sh"

PASTA="" CHAVE="" AMOSTRA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    --amostra) AMOSTRA="${2:-}"; shift 2 || falha "--amostra precisa de um número." ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) falha "opção desconhecida: $1 (veja --help)" ;;
    *) PASTA="$1"; shift ;;
  esac
done
[ -n "$PASTA" ] && [ -n "$CHAVE" ] || falha "uso: ensaiar_restauracao.sh <pasta do backup> --chave <identidade-age.txt>"
PASTA="$(absoluto "$PASTA")"; CHAVE="$(absoluto "$CHAVE")"
[ -d "$PASTA/arquivos" ] && [ -f "$CHAVE" ] || falha "pasta do backup (com arquivos/) ou identidade não encontradas."
[[ "$AMOSTRA" =~ ^[0-9]+$ ]] || falha "--amostra precisa de um número."
PACOTE="$(ls -1t "$PASTA"/fotos-*.tar.age 2>/dev/null | head -n 1)"
[ -n "$PACOTE" ] || falha "nenhum fotos-*.tar.age em $PASTA."

IMAGEM_PG="$(grep -E '^[[:space:]]*image:[[:space:]]*ghcr.io/immich-app/postgres' "$APP/fotos/docker-compose.yml" | head -n 1 | awk '{print $2}')"
[ -n "$IMAGEM_PG" ] || falha "não achei a imagem do Postgres do Immich em fotos/docker-compose.yml."

umask 077
BASE="${ENSAIO_PASTA:-$HOME}"
ENSAIO="$(mktemp -d "$BASE/.fotos-ensaio-XXXXXX")" || falha "não consegui criar a pasta do ensaio em $BASE."
CONTAINER="fotos-ensaio-$$"
LOG_GUARDADO="$BASE/fotos-ensaio-restauracao.log"
limpar() {
  local codigo=$?
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  if [ "$codigo" -ne 0 ] && [ -s "$ENSAIO/restauracao.log" ]; then
    cp "$ENSAIO/restauracao.log" "$LOG_GUARDADO" && echo "$NOME_SCRIPT: log do psql guardado em $LOG_GUARDADO" >&2
  fi
  rm -rf "$ENSAIO"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM

# --- 1. Pacote ----------------------------------------------------------------------------------------------------
log "abrindo $(basename "$PACOTE")"
if [ -f "$PACOTE.sha256" ]; then
  [ "$(sha256_de "$PACOTE")" = "$(awk '{print $1}' "$PACOTE.sha256")" ] || falha "o hash do pacote não bate com $PACOTE.sha256."
fi
mkdir -p "$ENSAIO/pacote"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$ENSAIO/pacote" -xf - || falha "não consegui decifrar ou abrir o pacote."
(cd "$ENSAIO/pacote" && sha256_conferir) || falha "SHA256SUMS do pacote não confere."
DUMP="$(ls -1 "$ENSAIO"/pacote/immich-db-backup-*.sql.gz 2>/dev/null | head -n 1)"
[ -n "$DUMP" ] || falha "o pacote não tem o dump do banco."
log "pacote ok: $(basename "$DUMP"), $(wc -l <"$ENSAIO/pacote/indice.tsv" | tr -d ' ') originais no índice"

# --- 2. Banco num Postgres descartável do Immich --------------------------------------------------------------------
log "restaurando o banco num Postgres descartável ($IMAGEM_PG)"
docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD=ensaio -e POSTGRES_USER=postgres -e POSTGRES_DB=immich \
  "$IMAGEM_PG" >/dev/null || falha "não consegui subir o Postgres do ensaio."
for _ in $(seq 1 60); do docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 || falha "o Postgres do ensaio não ficou pronto."
sleep 3
# Como na restauração da documentação do Immich: o dump zera o search_path, e o sed o devolve.
gunzip -c "$DUMP" \
  | sed "s/SELECT pg_catalog.set_config('search_path', '', false);/SELECT pg_catalog.set_config('search_path', 'public, pg_catalog', true);/g" \
  | docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=0 -U postgres -d postgres >"$ENSAIO/restauracao.log" 2>&1 \
  || falha "psql falhou."
# "já existe" é esperado (o dump recria o papel postgres e o banco); qualquer outro ERROR reprova.
erros_psql="$(grep -E 'ERROR' "$ENSAIO/restauracao.log" | grep -vcE 'already exists' || true)"
[ "$erros_psql" -eq 0 ] || falha "$erros_psql erros do psql na restauração (primeiros: $(grep -E 'ERROR' "$ENSAIO/restauracao.log" | grep -vE 'already exists' | head -n 3 | tr '\n' ' '))."
contar() { docker exec "$CONTAINER" psql -tA -U postgres -d immich -c "$1" 2>/dev/null | tr -d '\r '; }
usuarios="$(contar 'select count(*) from "user"')"
fotos_banco="$(contar 'select count(*) from asset where "deletedAt" is null')"
albuns="$(contar 'select count(*) from album where "deletedAt" is null')"
[ -n "$usuarios" ] && [ "$usuarios" -ge 1 ] || falha "o banco restaurado não tem usuários (tabela \"user\")."
[ -n "$fotos_banco" ] && [ -n "$albuns" ] || falha "não consegui contar as fotos ou os álbuns (tabelas asset e album)."
log "banco ok: $usuarios usuários, $fotos_banco fotos e vídeos ativos, $albuns álbuns"

# Cada foto do banco tem o original no backup (originalPath é /data/<library|upload>/...).
contar_linhas() { docker exec "$CONTAINER" psql -tA -U postgres -d immich -c "$1" 2>/dev/null | tr -d '\r'; }
contar_linhas 'select "originalPath" from asset where "deletedAt" is null' >"$ENSAIO/caminhos" \
  || falha "não consegui ler os caminhos das fotos."
sem_original=0
while IFS= read -r caminho; do
  [ -n "$caminho" ] || continue
  [ -s "$PASTA/arquivos/${caminho#/data/}.age" ] || { sem_original=$((sem_original + 1)); [ "$sem_original" -le 5 ] && aviso "foto do banco sem original no backup: $caminho"; }
done <"$ENSAIO/caminhos"
[ "$sem_original" -eq 0 ] || falha "$sem_original fotos do banco sem original no backup."

# --- 3. Originais ------------------------------------------------------------------------------------------------------
faltam=0
while IFS="$(printf '\t')" read -r rel _; do
  [ -s "$PASTA/arquivos/$rel.age" ] || { faltam=$((faltam + 1)); [ "$faltam" -le 5 ] && aviso "sem .age no backup: $rel"; }
done <"$ENSAIO/pacote/indice.tsv"
[ "$faltam" -eq 0 ] || falha "$faltam originais do índice sem .age no backup."

if [ "$AMOSTRA" -gt 0 ]; then
  sorteio() { awk 'BEGIN{srand()} {print rand() "\t" $0}' | sort -k1,1 | cut -f2- | head -n "$AMOSTRA"; }
else
  sorteio() { cat; }
fi
conferidos=0
mkdir -p "$ENSAIO/original"
while IFS="$(printf '\t')" read -r rel tam; do
  decifrar "$CHAVE" <"$PASTA/arquivos/$rel.age" >"$ENSAIO/original/f" || falha "não consegui decifrar $rel."
  [ "$(wc -c <"$ENSAIO/original/f" | tr -d ' ')" = "$tam" ] || falha "tamanho diferente do índice: $rel."
  conferidos=$((conferidos + 1))
done < <(sorteio <"$ENSAIO/pacote/indice.tsv")
rm -f "$ENSAIO/original/f"
log "originais ok: todas as fotos do banco e do índice com .age; $conferidos decifrados com o tamanho do índice"
log "ensaio ok"
