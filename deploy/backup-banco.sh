#!/usr/bin/env bash
# Backup do Postgres do assistente: pg_dump em formato custom (-Fc), datado, com retenção.
# Roda no host da stack (Mac ou produção), a partir de qualquer diretório. Não lê o .env:
# usuário e banco vêm das variáveis do próprio container.
#
# Variáveis (todas opcionais):
#   BACKUP_DIR        destino                       (padrão /srv/backups/postgres)
#   BACKUP_RETENCAO   quantos dumps manter          (padrão 14)
#   COMPOSE_DIR       pasta do docker-compose.yml   (padrão: pasta acima deste script)
#
# Só apaga arquivos com o nome que ele mesmo cria: assistente-AAAAMMDD-HHMMSS.dump
# Saída com código 0 só se o dump foi gravado e conferido (pg_restore --list).
set -u

BACKUP_DIR="${BACKUP_DIR:-/srv/backups/postgres}"
BACKUP_RETENCAO="${BACKUP_RETENCAO:-14}"
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

log() { echo "backup-banco: $*"; }
falha() { log "ERRO: $*"; exit 1; }

case "$BACKUP_RETENCAO" in
  ''|*[!0-9]*) falha "BACKUP_RETENCAO precisa ser um número inteiro (recebi '$BACKUP_RETENCAO')." ;;
esac
[ "$BACKUP_RETENCAO" -ge 1 ] || falha "BACKUP_RETENCAO precisa ser 1 ou mais."
[ -f "$COMPOSE_DIR/docker-compose.yml" ] || falha "sem docker-compose.yml em $COMPOSE_DIR."

dc() { docker compose --project-directory "$COMPOSE_DIR" -f "$COMPOSE_DIR/docker-compose.yml" "$@"; }

umask 077
mkdir -p "$BACKUP_DIR" || falha "não consegui criar $BACKUP_DIR."

CARIMBO="$(date +%Y%m%d-%H%M%S)"
FINAL="$BACKUP_DIR/assistente-$CARIMBO.dump"
PARCIAL="$FINAL.parcial"

log "gravando $FINAL"
dc exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >"$PARCIAL" \
  || { rm -f "$PARCIAL"; falha "pg_dump falhou (a stack está de pé? 'docker compose ps')."; }

[ -s "$PARCIAL" ] || { rm -f "$PARCIAL"; falha "o dump saiu vazio."; }

# Confere que o dump é legível e tem conteúdo (pg_restore dentro do container, sem restaurar nada).
ITENS="$(dc exec -T postgres pg_restore --list <"$PARCIAL" 2>/dev/null | grep -c ' TABLE DATA ')"
if [ "${ITENS:-0}" -lt 1 ]; then
  rm -f "$PARCIAL"
  falha "pg_restore --list não achou dados de tabela no dump."
fi

mv "$PARCIAL" "$FINAL" || falha "não consegui renomear o dump."
TAMANHO="$(wc -c <"$FINAL" | tr -d ' ')"
log "feito: $FINAL (${TAMANHO} bytes, ${ITENS} tabelas com dados)."

# Retenção: mantém os BACKUP_RETENCAO mais novos entre os arquivos de nome exato.
# O carimbo no nome ordena por data; nada fora desse padrão é tocado.
APAGAR="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'assistente-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].dump' \
  | sort -r | tail -n +"$((BACKUP_RETENCAO + 1))")"
if [ -n "$APAGAR" ]; then
  echo "$APAGAR" | while IFS= read -r velho; do
    rm -f -- "$velho" && log "apagado (passou da retenção de $BACKUP_RETENCAO): $velho"
  done
fi

# --- Gancho da Fase 7: cópia para outra máquina (ainda desligado) ------------------------------
# O backup no mesmo disco não protege contra perda do disco. Na Fase 7, copie para fora daqui:
#   rsync -a --ignore-existing "$BACKUP_DIR/" <usuario>@<destino>:/srv/backups/assistente-postgres/
# ou um HD avulso montado. Só ligue depois de testar a restauração (deploy/restaurar-banco.sh).

exit 0
