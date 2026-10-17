#!/usr/bin/env bash
# Restaura um dump do backup-banco.sh num banco NOVO. Nunca sobrescreve o banco "assistente".
# Serve para testar o backup e para levar os dados do Mac para a produção (B10).
#   bash deploy/restaurar-banco.sh <arquivo.dump> <nome_do_banco_novo>
# Exemplo: bash deploy/restaurar-banco.sh /srv/backups/postgres/assistente-20261018-030000.dump assistente_mac
#
# Recusa: banco que já existe, nome "assistente", "postgres" e "template*".
# Depois de conferir, apague o banco de teste:
#   docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" <nome>'
set -u

COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

log() { echo "restaurar-banco: $*"; }
falha() { log "ERRO: $*"; exit 1; }

[ "$#" -eq 2 ] || { sed -n '2,6p' "$0"; exit 2; }
ARQUIVO="$1"
NOVO="$2"

[ -s "$ARQUIVO" ] || falha "arquivo inexistente ou vazio: $ARQUIVO"
printf '%s' "$NOVO" | grep -Eq '^[a-z][a-z0-9_]{0,62}$' \
  || falha "nome inválido '$NOVO' (use minúsculas, números e _, começando por letra)."
case "$NOVO" in
  assistente|postgres|template*) falha "o nome '$NOVO' é reservado; escolha outro." ;;
esac
[ -f "$COMPOSE_DIR/docker-compose.yml" ] || falha "sem docker-compose.yml em $COMPOSE_DIR."

dc() { docker compose --project-directory "$COMPOSE_DIR" -f "$COMPOSE_DIR/docker-compose.yml" "$@"; }

EXISTE="$(echo "select 1 from pg_database where datname = :'n'" \
  | dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -At -v n="$1"' sh "$NOVO" 2>/dev/null)"
[ "$?" -eq 0 ] || falha "não consegui falar com o Postgres (a stack está de pé?)."
[ -z "$EXISTE" ] || falha "o banco '$NOVO' já existe; não sobrescrevo. Apague-o ou escolha outro nome."

log "criando o banco $NOVO"
dc exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$NOVO" || falha "createdb falhou."

log "restaurando $ARQUIVO em $NOVO"
if ! dc exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error' sh "$NOVO" <"$ARQUIVO"; then
  falha "pg_restore falhou. O banco '$NOVO' ficou pela metade; apague-o (veja o topo deste script)."
fi

# Mesmo acesso de conexão que o banco original tem para os usuários da aplicação (se existirem).
dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -q -v ON_ERROR_STOP=1 -c "GRANT CONNECT ON DATABASE \"$1\" TO assistente_leitura, assistente_escrita"' sh "$NOVO" \
  >/dev/null 2>&1 || log "aviso: não dei CONNECT a assistente_leitura/escrita (papéis ausentes?)."

log "feito. Linhas por tabela em $NOVO:"
dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$1" -At' sh "$NOVO" <<'SQL' \
  || log "(contagem por tabela indisponível)"
select relname || ': ' || (xpath('/row/cnt/text()',
  query_to_xml(format('select count(*) as cnt from %I', relname), false, true, '')))[1]::text
from pg_stat_user_tables order by relname;
SQL
exit 0
