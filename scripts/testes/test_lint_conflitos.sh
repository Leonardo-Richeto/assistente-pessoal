#!/usr/bin/env bash
# Teste dos avisos do lint diário (conflito do Syncthing, index.lock esquecido, commit diário parado), com um lint
# falso (sem vault real).
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

# Roda o lint-diario.sh sobre o vault e imprime o código de saída. Sem CARIMBO_COMMIT, um carimbo que não existe.
rodar() {  # <nome do vault>
  CARIMBO_COMMIT="${CARIMBO_COMMIT:-$RAIZ/sem-carimbo}" VAULT_PATH="$RAIZ/$1" LINT_DIR="$RAIZ/logs-$1" bash "$SCRIPT" >/dev/null 2>&1
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

# (f) última execução limpa do commit diário (carimbo do commit-diario.sh) há 5 dias: AVISO com os dias, código 0.
# (g) carimbo de hoje (mesmo sem commit diário há dias: vault sem mudança), ou sem carimbo: sem aviso.
carimbo() {  # <arquivo> <segundos atrás>
  echo $(( $(date +%s) - $2 )) >"$1"
}
v="$(novo_vault diario-velho)"
carimbo "$RAIZ/carimbo-velho" $(( 5 * 86400 + 3600 ))
codigo="$(CARIMBO_COMMIT="$RAIZ/carimbo-velho" rodar diario-velho)"
if [ "$codigo" -eq 0 ] && grep -qF "AVISO: última execução limpa do commit diário há 5 dias." "$RAIZ/logs-diario-velho/ultimo.md"; then
  echo "ok commit diário parado: aviso com os dias e código 0"
else
  echo "FALHOU: commit diário parado, código $codigo ou aviso ausente"; falhas=$((falhas + 1))
fi
# Vault sem mudança há 5 dias: o último commit diário é velho, mas a execução de hoje saiu limpa.
v="$(novo_vault diario-novo)"
git -C "$v" -c init.defaultBranch=main init -q
echo "x" >>"$v/00-inbox/dia.md"
git -C "$v" add -A
velho="$(python3 -c 'import datetime as d; print((d.datetime.now() - d.timedelta(days=5)).isoformat(timespec="seconds"))')"
GIT_AUTHOR_DATE="$velho" GIT_COMMITTER_DATE="$velho" GIT_CONFIG_GLOBAL=/dev/null git -C "$v" \
  -c user.name="Vault (commit diário)" -c user.email=vault@localhost -c commit.gpgsign=false commit -q -m "vault: velho"
carimbo "$RAIZ/carimbo-novo" 60
codigo="$(CARIMBO_COMMIT="$RAIZ/carimbo-novo" rodar diario-novo)"
v="$(novo_vault sem-carimbo)"
codigo2="$(CARIMBO_COMMIT="$RAIZ/nao-existe" rodar sem-carimbo)"
if [ "$codigo" -eq 0 ] && ! grep -q "commit diário" "$RAIZ/logs-diario-novo/ultimo.md" \
  && [ "$codigo2" -eq 0 ] && ! grep -q "commit diário" "$RAIZ/logs-sem-carimbo/ultimo.md"; then
  echo "ok execução limpa recente (vault sem mudança) ou sem carimbo: sem aviso"
else
  echo "FALHOU: aviso de commit diário indevido (códigos $codigo e $codigo2)"; falhas=$((falhas + 1))
fi

[ "$falhas" -eq 0 ] && echo "test_lint_conflitos: ok" || { echo "test_lint_conflitos: $falhas falha(s)"; exit 1; }
