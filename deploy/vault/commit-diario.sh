#!/usr/bin/env bash
# Commit diário do vault (histórico de tudo que a IA e o Leonardo escreveram).
# Só comita se houver mudança. Só faz push se VAULT_PUSH=1. Não apaga nada.
# Antes do commit, o gitleaks (numa imagem Docker com versão e digest fixos, sem rede, vault só leitura) varre o
# que está no stage. Achou segredo, ou não conseguiu rodar: tira do stage (`git reset`, nada se perde no disco),
# não comita e sai 1 (falha fechado). O relatório (com --redact, sem o valor) fica em LOG_DIR, fora do vault.
# Chamado pelo vault-commit.service; também roda à mão:
#   VAULT_PATH=/srv/assistente/vault bash deploy/vault/commit-diario.sh
# Saída vai para o journal: journalctl -u vault-commit.service
set -u

VAULT_PATH="${VAULT_PATH:-/srv/assistente/vault}"
VAULT_PUSH="${VAULT_PUSH:-0}"
LOG_DIR="${LOG_DIR:-/srv/assistente/logs/vault-commit}"
# gitleaks v8.30.1 (2026-03-21). Digest do índice multi-arquitetura (amd64 e arm64), conferido com
# `docker buildx imagetools inspect` em 2026-10-22. Para atualizar: leia o changelog, troque os dois juntos.
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f}"
GITLEAKS_ACHOU=3  # código de saída do gitleaks quando acha segredo; qualquer outro diferente de 0 é falha dele

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

# Tira tudo do stage (o disco fica igual: nada se perde) e diz por que não comitou.
nao_comitar() {  # <motivo>
  "${GIT[@]}" reset -q || log "ERRO: git reset falhou; o stage ficou com as mudanças de hoje."
  log "ERRO: $1; nada foi comitado hoje."
}

# gitleaks no que está no stage. 0 = limpo; 1 = achou ou falhou (já tirou do stage e logou).
varrer_segredos() {
  # Config e lista de ignorados do gitleaks vindas do vault (Syncthing) desligariam a varredura: recusa.
  local f
  for f in .gitleaks.toml .gitleaksignore; do
    if [ -e "$f" ]; then nao_comitar "o vault tem $f (desligaria regras do gitleaks); tire o arquivo"; return 1; fi
  done
  if ! command -v docker >/dev/null 2>&1; then
    nao_comitar "docker não está disponível; o gitleaks não rodou"; return 1
  fi
  if ! mkdir -p "$LOG_DIR" 2>/dev/null || [ ! -w "$LOG_DIR" ]; then
    nao_comitar "não consigo escrever o relatório em $LOG_DIR; o gitleaks não rodou"; return 1
  fi
  local relatorio="$LOG_DIR/gitleaks.json" saida="$LOG_DIR/gitleaks.log" codigo
  rm -f "$relatorio"
  # Sem rede, só leitura, sem privilégio, com o uid do dono do vault. O git de dentro da imagem não usa ganchos,
  # fsmonitor nem diff externo do repositório (GIT_CONFIG_* vale como `-c`). `gitleaks:allow` na nota não vale.
  docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" \
    -v "$VAULT_PATH:/vault:ro" -v "$LOG_DIR:/relatorio" \
    -e GIT_CONFIG_COUNT=5 \
    -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/vault \
    -e GIT_CONFIG_KEY_1=core.hooksPath -e GIT_CONFIG_VALUE_1=/dev/null \
    -e GIT_CONFIG_KEY_2=core.fsmonitor -e GIT_CONFIG_VALUE_2=false \
    -e GIT_CONFIG_KEY_3=diff.external -e GIT_CONFIG_VALUE_3= \
    -e GIT_CONFIG_KEY_4=core.sshCommand -e GIT_CONFIG_VALUE_4=false \
    "$GITLEAKS_IMAGE" git --staged --redact --no-banner --no-color --ignore-gitleaks-allow \
    --gitleaks-ignore-path /nao-existe --exit-code "$GITLEAKS_ACHOU" --timeout 600 \
    --report-format json --report-path /relatorio/gitleaks.json /vault >"$saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 0 ]; then
    log "gitleaks: nada com cara de segredo."
    return 0
  fi
  if [ "$codigo" -eq "$GITLEAKS_ACHOU" ]; then
    local arquivos
    arquivos="$(grep -o '"File": *"[^"]*"' "$relatorio" 2>/dev/null | sed 's/^"File": *"//; s/"$//' | sort -u \
      | paste -sd ',' - | sed 's/,/, /g')"
    nao_comitar "gitleaks achou segredo em: ${arquivos:-(veja $relatorio)}"
    return 1
  fi
  nao_comitar "gitleaks não rodou (docker run saiu com $codigo; veja $saida)"
  return 1
}

if [ -z "$("${GIT[@]}" status --porcelain)" ]; then
  log "sem mudanças em $(date +%F); nada a comitar."
else
  # Exclui o que o Syncthing deixa na pasta (versões, marcador, temporários) e um .git guardado por engano.
"${GIT[@]}" add -A -- . ':!.stversions' ':!.stfolder' ':!*.syncthing.*.tmp' ':!.git-mac-parado' || { log "ERRO: git add falhou."; exit 1; }
  varrer_segredos || exit 1
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
