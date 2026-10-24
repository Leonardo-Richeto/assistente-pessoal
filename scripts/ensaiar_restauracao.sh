#!/usr/bin/env bash
# Ensaio de restauração (PLANO 7.2): prova que um pacote do backup abre e que o banco volta inteiro,
# sem tocar em nenhuma instalação. Roda em qualquer máquina com docker (Mac, i7, Windows com Git Bash).
#
#   scripts/ensaiar_restauracao.sh <pacote.tar.age> --chave <identidade-age.txt>
#
# O que faz, numa pasta temporária apagada no fim:
#   1. decifra o pacote e confere o SHA256SUMS;
#   2. sobe um Postgres descartável (mesma imagem do compose, sem porta, sem volume) e restaura o
#      banco.dump sem dono nem GRANTs;
#   3. compara as linhas por tabela com o contagens.tsv do pacote;
#   4. confere que o vault.tar abre e que o git do vault está íntegro.
# O pacote traz o .env com as senhas: ele só existe na pasta temporária e nunca é mostrado.

source "$(dirname "$0")/lib.sh"

PACOTE="" CHAVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    -*) falha "opção desconhecida: $1 (veja --help)" ;;
    *) PACOTE="$1"; shift ;;
  esac
done
[ -n "$PACOTE" ] || falha "falta o pacote (veja --help)."
[ -n "$CHAVE" ] || falha "falta --chave <identidade-age.txt>."
PACOTE="$(absoluto "$PACOTE")"; CHAVE="$(absoluto "$CHAVE")"
[ -f "$PACOTE" ] || falha "pacote não encontrado: $PACOTE"
[ -f "$CHAVE" ] || falha "identidade não encontrada: $CHAVE"

TMP="$(mktemp -d)"
PG="ensaio-restauracao-$$"
limpar() { docker rm -f "$PG" >/dev/null 2>&1; rm -rf "$TMP"; }
trap limpar EXIT

log "decifrando $(basename "$PACOTE")"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$TMP" -xf - || falha "não consegui decifrar ou abrir o pacote."
(cd "$TMP" && sha256_conferir) || falha "SHA256SUMS não confere."
log "SHA256SUMS confere"
grep -E '"(schema|commit|criado_em|maquina)"' "$TMP/manifesto.json" | sed 's/^ */  /'

log "subindo um Postgres descartável ($(imagem_postgres))"
docker run -d --name "$PG" -e POSTGRES_PASSWORD=ensaio -e POSTGRES_DB=ensaio "$(imagem_postgres)" >/dev/null \
  || falha "não consegui subir o Postgres."
for _ in $(seq 60); do docker exec "$PG" pg_isready -q -h 127.0.0.1 -U postgres && break; sleep 1; done
docker exec "$PG" pg_isready -q -h 127.0.0.1 -U postgres || falha "o Postgres não ficou pronto."

log "restaurando banco.dump"
docker exec -i "$PG" pg_restore -U postgres -d ensaio --no-owner --no-privileges --exit-on-error <"$TMP/banco.dump" \
  || falha "pg_restore falhou."

docker exec -i "$PG" psql -U postgres -d ensaio -At -F $'\t' >"$TMP/contagens-ensaio.tsv" <<'SQL' \
  || falha "não consegui contar as linhas."
select c.relname,
       (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from public.%I', c.relname), false, true, '')))[1]::text
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'p')
order by c.relname;
SQL
diff <(tr -d '\r' <"$TMP/contagens.tsv") "$TMP/contagens-ensaio.tsv" >&2 \
  || falha "as linhas por tabela não batem com o contagens.tsv do pacote."
log "banco restaurado: linhas iguais às do pacote ($(wc -l <"$TMP/contagens.tsv" | tr -d ' ') tabelas)"
sed 's/^/  /' "$TMP/contagens-ensaio.tsv"

mkdir "$TMP/vault-ensaio"
tar -C "$TMP/vault-ensaio" -xf "$TMP/vault.tar" || falha "vault.tar não abre."
NOTAS="$(find "$TMP/vault-ensaio/vault" -name '*.md' -not -path '*/.git/*' | wc -l | tr -d ' ')"
git -C "$TMP/vault-ensaio/vault" fsck --no-progress >/dev/null 2>&1 || falha "git do vault com erro (git fsck)."
log "vault abre: $NOTAS notas, git íntegro, último commit $(git -C "$TMP/vault-ensaio/vault" log -1 --format='%h %cs')"

log "ensaio ok: o pacote abre e o banco volta inteiro. Pasta temporária e Postgres apagados."
