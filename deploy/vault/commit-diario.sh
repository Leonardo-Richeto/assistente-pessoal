#!/usr/bin/env bash
# Commit diário do vault (histórico de tudo que a IA e o Leonardo escreveram).
# Só comita se houver mudança. Só faz push se VAULT_PUSH=1. Não apaga nada.
# Chamado pelo vault-commit.service; também roda à mão:
#   VAULT_PATH=/srv/vault bash deploy/vault/commit-diario.sh
# Saída vai para o journal: journalctl -u vault-commit.service
set -u

VAULT_PATH="${VAULT_PATH:-/srv/vault}"
VAULT_PUSH="${VAULT_PUSH:-0}"

log() { echo "vault-commit: $*"; }

[ -d "$VAULT_PATH/.git" ] || { log "ERRO: $VAULT_PATH não é um repositório git."; exit 1; }
cd "$VAULT_PATH" || exit 1

# Nome e e-mail só para este commit; não altera a config do repositório.
GIT=(git -c user.name="Vault (commit diário)" -c user.email="vault@localhost")

if [ -z "$(git status --porcelain)" ]; then
  log "sem mudanças em $(date +%F); nada a comitar."
else
  # Exclui o que o Syncthing deixa na pasta (versões, marcador, temporários) e um .git guardado por engano.
"${GIT[@]}" add -A -- . ':!.stversions' ':!.stfolder' ':!*.syncthing.*.tmp' ':!.git-mac-parado' || { log "ERRO: git add falhou."; exit 1; }
  N="$(git diff --cached --name-only | wc -l | tr -d ' ')"
  "${GIT[@]}" commit -q -m "vault: $(date +%F) (${N} arquivos)" || { log "ERRO: git commit falhou."; exit 1; }
  log "commit feito em $(date +%F): ${N} arquivos."
fi

if [ "$VAULT_PUSH" = "1" ]; then
  if git push; then
    log "push feito."
  else
    log "ERRO: git push falhou (credencial ou rede). O commit local ficou."
    exit 1
  fi
else
  log "push desligado (VAULT_PUSH não é 1)."
fi
