#!/usr/bin/env bash
# Lista das notas marcadas como desatualizadas no banco (marcar_desatualizada), para o lint diário.
# Grava $LINT_DIR/marcas.md: uma linha por marca em vigor, vazio sem marca, ou a linha de AVISO se a
# consulta falhou. O lint-diario.sh junta esse arquivo ao relatório.
# Chamado pelo vault-marcas.service (03:35, antes do lint das 03:40); também roda à mão:
#   ASSISTENTE_DIR=/srv/assistente/app LINT_DIR=/srv/assistente/logs/vault-lint bash deploy/vault/marcas-desatualizadas.sh
# Este script precisa de docker (= root) e só roda código do repositório. O lint roda código que vem do
# vault (90-meta/lint-do-vault.py, pelo Syncthing): por isso a consulta ao banco fica aqui, e não no lint.
# Sai com o código da consulta (diferente de 0 = falhou), para aparecer em `systemctl --failed`.
set -u

ASSISTENTE_DIR="${ASSISTENTE_DIR:-/srv/assistente/app}"
LINT_DIR="${LINT_DIR:-/srv/assistente/logs/vault-lint}"

log() { echo "vault-marcas: $*"; }

mkdir -p "$LINT_DIR" || { log "ERRO: não consegui criar $LINT_DIR."; exit 2; }
# mktemp cria um arquivo novo (O_EXCL): um link deixado na pasta por outro usuário não é seguido.
PARCIAL="$(mktemp "$LINT_DIR/marcas.md.parcial.XXXXXX")" || { log "ERRO: não consegui gravar em $LINT_DIR."; exit 2; }
trap 'rm -f "$PARCIAL"' EXIT

docker compose --project-directory "$ASSISTENTE_DIR" exec -T servidor \
  python -m assistente.desatualizadas >"$PARCIAL"  # o stderr vai para o journal do serviço
CODIGO=$?
if [ "$CODIGO" -ne 0 ]; then
  echo "AVISO: não consegui consultar as marcas ($CODIGO)." >"$PARCIAL"
fi
chmod 0644 "$PARCIAL"  # o lint pode rodar com outro usuário
mv -f "$PARCIAL" "$LINT_DIR/marcas.md"
if [ "$CODIGO" -ne 0 ]; then
  log "ERRO: a consulta falhou (código $CODIGO); o lint vai mostrar o aviso."
else
  log "$(grep -c . "$LINT_DIR/marcas.md") marca(s). Arquivo: $LINT_DIR/marcas.md"
fi
exit "$CODIGO"
