#!/usr/bin/env bash
# Teste do commit diário do vault (deploy/vault/commit-diario.sh) num repositório temporário (sem vault real):
# config do repositório que rodaria comando não roda, e o index.lock de um commit em andamento é esperado.
#   bash scripts/testes/test_commit_diario.sh
set -u

SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault/commit-diario.sh"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
falhas=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

# Cria um vault com git e um commit inicial e imprime o caminho.
novo_vault() {  # <nome>
  local v="$RAIZ/$1"
  mkdir -p "$v/00-inbox"
  echo "# A" >"$v/00-inbox/a.md"
  git -C "$v" -c init.defaultBranch=main init -q
  git -C "$v" add -A
  git -C "$v" -c user.name=T -c user.email=t@l -c commit.gpgsign=false commit -q -m inicial
  echo "$v"
}

# Script que cria um arquivo-marca; imprime o caminho do script.
marca() {  # <nome>
  local s="$RAIZ/roda-$1.sh"
  printf '#!/bin/sh\n: > "%s"\n' "$RAIZ/marca-$1" >"$s"
  chmod +x "$s"
  echo "$s"
}

# (a) ganchos, fsmonitor e sshCommand do repositório não rodam; o commit sai.
v="$(novo_vault cfg)"
mkdir -p "$RAIZ/ganchos"
for g in pre-commit post-commit commit-msg; do cp "$(marca "$g")" "$RAIZ/ganchos/$g"; done
git -C "$v" config core.hooksPath "$RAIZ/ganchos"
git -C "$v" config core.fsmonitor "$(marca fsmonitor)"
git -C "$v" config core.sshCommand "$(marca ssh)"
echo "mudou" >>"$v/00-inbox/a.md"
VAULT_PATH="$v" VAULT_PUSH=0 bash "$SCRIPT" >/dev/null 2>&1
codigo=$?
n="$(git -C "$v" rev-list --count HEAD)"
marcas="$(ls "$RAIZ" | grep '^marca-' || true)"
if [ "$codigo" -eq 0 ] && [ "$n" -eq 2 ] && [ -z "$marcas" ]; then
  echo "ok config do repositório não roda comando"
else
  echo "FALHOU: código $codigo, $n commits, marcas: ${marcas:-nenhuma}"; falhas=$((falhas + 1))
fi

# (b) index.lock de um commit em andamento: espera ele sair e comita.
v="$(novo_vault lock)"
echo "mudou" >>"$v/00-inbox/a.md"
: >"$v/.git/index.lock"
( sleep 2; rm -f "$v/.git/index.lock" ) &
VAULT_PATH="$v" VAULT_PUSH=0 bash "$SCRIPT" >/dev/null 2>&1
codigo=$?
wait
n="$(git -C "$v" rev-list --count HEAD)"
if [ "$codigo" -eq 0 ] && [ "$n" -eq 2 ]; then
  echo "ok espera o index.lock e comita"
else
  echo "FALHOU: com index.lock temporário, código $codigo e $n commits"; falhas=$((falhas + 1))
fi

[ "$falhas" -eq 0 ] && echo "test_commit_diario: ok" || { echo "test_commit_diario: $falhas falha(s)"; exit 1; }
