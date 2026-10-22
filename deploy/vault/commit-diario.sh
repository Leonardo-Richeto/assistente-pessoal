#!/usr/bin/env bash
# Commit diário do vault (histórico de tudo que a IA e o Leonardo escreveram).
# Só comita se houver mudança. Só faz push se VAULT_PUSH=1. Não apaga nada.
# Chamado pelo vault-commit.service; também roda à mão:
#   VAULT_PATH=/srv/assistente/vault bash deploy/vault/commit-diario.sh
# Saída vai para o journal: journalctl -u vault-commit.service
set -u

VAULT_PATH="${VAULT_PATH:-/srv/assistente/vault}"
VAULT_PUSH="${VAULT_PUSH:-0}"

log() { echo "vault-commit: $*"; }

[ -d "$VAULT_PATH/.git" ] || { log "ERRO: $VAULT_PATH não é um repositório git."; exit 1; }
cd "$VAULT_PATH" || exit 1

# Config do repositório que rodaria comando (ganchos, fsmonitor, ssh) não vale aqui: o .git fica na pasta que o
# container também escreve. Nome e e-mail só para este commit; não altera a config do repositório.
SEGURO=(-c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.sshCommand=false)
GIT=(git "${SEGURO[@]}" -c user.name="Vault (commit diário)" -c user.email="vault@localhost")

# O servidor pode estar comitando uma escrita da IA: espera o index.lock sair (até 60 s, de 5 em 5).
ESPERA=0
while [ -e .git/index.lock ] && [ "$ESPERA" -lt 60 ]; do
  sleep 5
  ESPERA=$((ESPERA + 5))
done
[ -e .git/index.lock ] && { log "ERRO: .git/index.lock ocupado há mais de 60 s; nada comitado (o lint diário avisa)."; exit 1; }

if [ -z "$("${GIT[@]}" status --porcelain)" ]; then
  log "sem mudanças em $(date +%F); nada a comitar."
else
  # Exclui o que o Syncthing deixa na pasta (versões, marcador, temporários) e um .git guardado por engano.
"${GIT[@]}" add -A -- . ':!.stversions' ':!.stfolder' ':!*.syncthing.*.tmp' ':!.git-mac-parado' || { log "ERRO: git add falhou."; exit 1; }
  N="$("${GIT[@]}" diff --cached --name-only | wc -l | tr -d ' ')"
  "${GIT[@]}" commit -q --no-verify -m "vault: $(date +%F) (${N} arquivos)" || { log "ERRO: git commit falhou."; exit 1; }
  log "commit feito em $(date +%F): ${N} arquivos."
fi

if [ "$VAULT_PUSH" = "1" ]; then
  # ssh comum aqui (o push precisa dele); o core.sshCommand do repositório não vale.
  if git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.sshCommand=ssh push; then
    log "push feito."
  else
    log "ERRO: git push falhou (credencial ou rede). O commit local ficou."
    exit 1
  fi
else
  log "push desligado (VAULT_PUSH não é 1)."
fi
