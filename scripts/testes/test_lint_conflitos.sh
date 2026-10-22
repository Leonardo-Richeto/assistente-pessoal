#!/usr/bin/env bash
# Teste dos avisos do lint diário (conflito do Syncthing, index.lock esquecido), com um lint falso (sem vault real).
#   bash scripts/testes/test_lint_conflitos.sh
set -u

SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault/lint-diario.sh"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
falhas=0
CONFLITO="00-inbox/nota.sync-conflict-20261020-123456-ABCDEFG.md"

# Cria um vault com o lint falso (3 linhas, a 3ª é o resumo) e imprime o caminho.
novo_vault() {  # <nome>
  local v="$RAIZ/$1"
  mkdir -p "$v/90-meta" "$v/00-inbox"
  printf '%s\n' 'import sys' 'print("Lint falso")' 'print("Notas: 1")' 'print("Resumo: 0 ERRO")' 'sys.exit(0)' \
    > "$v/90-meta/lint-do-vault.py"
  echo "$v"
}

# Roda o lint-diario.sh sobre o vault e imprime o código de saída.
rodar() {  # <nome do vault>
  VAULT_PATH="$RAIZ/$1" LINT_DIR="$RAIZ/logs-$1" bash "$SCRIPT" >/dev/null 2>&1
  echo $?
}

# (a) sem conflito: sem seção no relatório.
v="$(novo_vault sem)"
codigo="$(rodar sem)"
if [ "$codigo" -eq 0 ] && ! grep -q "Conflitos do Syncthing" "$RAIZ/logs-sem/ultimo.md"; then
  echo "ok sem conflito: relatório sem seção"
else
  echo "FALHOU: sem conflito, código $codigo e seção presente ou relatório ausente"; falhas=$((falhas + 1))
fi

# (b) com conflito na pasta de notas: seção, caminho e código 0.
v="$(novo_vault com)"
touch "$v/$CONFLITO"
codigo="$(rodar com)"
relatorio="$RAIZ/logs-com/ultimo.md"
if [ "$codigo" -ne 0 ]; then
  echo "FALHOU: com conflito, código de saída $codigo (esperado 0)"; falhas=$((falhas + 1))
elif ! grep -q "^## Conflitos do Syncthing$" "$relatorio"; then
  echo "FALHOU: com conflito, seção ausente no relatório"; falhas=$((falhas + 1))
elif ! grep -qF "AVISO: 1 arquivo(s) de conflito." "$relatorio"; then
  echo "FALHOU: com conflito, aviso com a contagem ausente"; falhas=$((falhas + 1))
elif ! grep -qxF -- "- $CONFLITO" "$relatorio"; then
  echo "FALHOU: com conflito, caminho relativo ausente na lista"; falhas=$((falhas + 1))
else
  echo "ok com conflito: seção, caminho relativo e código 0"
fi

# (c) conflito dentro de .stversions/ não conta.
v="$(novo_vault stv)"
mkdir -p "$v/.stversions/00-inbox"
touch "$v/.stversions/00-inbox/nota.sync-conflict-20261020-123456-ABCDEFG.md"
codigo="$(rodar stv)"
if [ "$codigo" -eq 0 ] && ! grep -q "Conflitos do Syncthing" "$RAIZ/logs-stv/ultimo.md"; then
  echo "ok .stversions ignorado"
else
  echo "FALHOU: arquivo em .stversions/ entrou no aviso"; falhas=$((falhas + 1))
fi

# (d) .git/index.lock com mais de 10 minutos: AVISO no relatório, código 0.
v="$(novo_vault lockvelho)"
mkdir -p "$v/.git"
touch -t 202001010000 "$v/.git/index.lock"
codigo="$(rodar lockvelho)"
if [ "$codigo" -eq 0 ] && grep -qF "AVISO: .git/index.lock existe há mais de 10 minutos" "$RAIZ/logs-lockvelho/ultimo.md"; then
  echo "ok index.lock velho: aviso e código 0"
else
  echo "FALHOU: index.lock velho, código $codigo ou aviso ausente"; falhas=$((falhas + 1))
fi

# (e) .git/index.lock recente (um commit em andamento): sem aviso.
v="$(novo_vault locknovo)"
mkdir -p "$v/.git"
touch "$v/.git/index.lock"
codigo="$(rodar locknovo)"
if [ "$codigo" -eq 0 ] && ! grep -q "index.lock" "$RAIZ/logs-locknovo/ultimo.md"; then
  echo "ok index.lock recente: sem aviso"
else
  echo "FALHOU: index.lock recente gerou aviso (código $codigo)"; falhas=$((falhas + 1))
fi

[ "$falhas" -eq 0 ] && echo "test_lint_conflitos: ok" || { echo "test_lint_conflitos: $falhas falha(s)"; exit 1; }
