#!/usr/bin/env bash
# Lint diário do vault: roda o 90-meta/lint-do-vault.py do próprio vault e guarda o relatório.
# Só lê o vault; não muda nota nenhuma. Sai com o código do lint (1 = há ERRO), para o
# systemd marcar o serviço como falho e aparecer em `systemctl --failed`.
# Chamado pelo vault-lint.service; também roda à mão:
#   VAULT_PATH=/srv/assistente/vault LINT_DIR=/srv/assistente/logs/vault-lint bash deploy/vault/lint-diario.sh
# O relatório fica FORA do vault, para não virar nota nem entrar no commit diário.
set -u

VAULT_PATH="${VAULT_PATH:-/srv/assistente/vault}"
LINT_DIR="${LINT_DIR:-/srv/assistente/logs/vault-lint}"
LINT="$VAULT_PATH/90-meta/lint-do-vault.py"

log() { echo "vault-lint: $*"; }

command -v python3 >/dev/null || { log "ERRO: python3 não instalado (sudo apt-get install -y python3)."; exit 2; }
[ -f "$LINT" ] || { log "ERRO: $LINT não existe (o vault está em $VAULT_PATH?)."; exit 2; }
mkdir -p "$LINT_DIR" || { log "ERRO: não consegui criar $LINT_DIR."; exit 2; }

# -I: o Python não carrega módulo da pasta do vault, que recebe arquivo de vários aparelhos.
python3 -I "$LINT" --vault "$VAULT_PATH" >"$LINT_DIR/ultimo.md.parcial"
CODIGO=$?
if [ "$CODIGO" -gt 1 ]; then
  rm -f "$LINT_DIR/ultimo.md.parcial"
  log "ERRO: o lint quebrou (código $CODIGO); o relatório anterior ficou."
  exit "$CODIGO"
fi
mv "$LINT_DIR/ultimo.md.parcial" "$LINT_DIR/ultimo.md"
log "$(sed -n 3p "$LINT_DIR/ultimo.md") Relatório: $LINT_DIR/ultimo.md"
exit "$CODIGO"
