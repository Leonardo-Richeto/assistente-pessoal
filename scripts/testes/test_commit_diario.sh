#!/usr/bin/env bash
# Teste do commit diário do vault (deploy/vault/commit-diario.sh) num repositório temporário (sem vault real):
# config do repositório que rodaria comando não roda, o index.lock de um commit em andamento é esperado, e o
# gitleaks (com um `docker` falso) barra o commit quando acha segredo, falha ou não existe.
#   bash scripts/testes/test_commit_diario.sh
#   COM_DOCKER_REAL=1 bash scripts/testes/test_commit_diario.sh   # também roda a imagem real do gitleaks
set -u

SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault/commit-diario.sh"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
falhas=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export LOG_DIR="$RAIZ/logs"
# Chave AWS inventada, montada em partes (scanner de repositório não acusa este arquivo).
CHAVE_FALSA="AKIA""Q3EGUJ7KZP2WXY5T"

# docker falso: grava os argumentos e age conforme $DOCKER_FALSO (limpo, achou, quebrado).
BIN_FALSO="$RAIZ/bin-falso"
mkdir -p "$BIN_FALSO"
cat >"$BIN_FALSO/docker" <<'FALSO'
#!/bin/bash
printf '%s\n' "$@" >"$LOG_DIR/docker-args"
case "${DOCKER_FALSO:-limpo}" in
  limpo) exit 0 ;;
  achou) printf '[\n {\n  "File": "b.md",\n  "Secret": "REDACTED"\n },\n {\n  "File": "pasta/c d.md",\n  "Secret": "REDACTED"\n }\n]\n' \
           >"$LOG_DIR/gitleaks.json"; exit 3 ;;
  quebrado) echo "Unable to find image" >&2; exit 125 ;;
esac
FALSO
chmod +x "$BIN_FALSO/docker"
PATH_FALSO="$BIN_FALSO:$PATH"

# PATH só com o que o script usa, sem docker (link para cada comando).
SEM_DOCKER="$RAIZ/bin-sem-docker"
mkdir -p "$SEM_DOCKER"
for c in git date wc tr sleep mkdir rm id grep sed sort paste cat; do ln -s "$(command -v "$c")" "$SEM_DOCKER/$c"; done

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
PATH="$PATH_FALSO" VAULT_PATH="$v" VAULT_PUSH=0 bash "$SCRIPT" >/dev/null 2>&1
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
PATH="$PATH_FALSO" VAULT_PATH="$v" VAULT_PUSH=0 bash "$SCRIPT" >/dev/null 2>&1
codigo=$?
wait
n="$(git -C "$v" rev-list --count HEAD)"
if [ "$codigo" -eq 0 ] && [ "$n" -eq 2 ]; then
  echo "ok espera o index.lock e comita"
else
  echo "FALHOU: com index.lock temporário, código $codigo e $n commits"; falhas=$((falhas + 1))
fi

# Roda o script com o docker falso no modo dado; deixa a saída em $RAIZ/saida e o código em $codigo.
rodar() {  # <vault> <modo do docker falso> [PATH]
  PATH="${3:-$PATH_FALSO}" DOCKER_FALSO="$2" VAULT_PATH="$1" VAULT_PUSH=0 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
}

# Não comitou, nada no stage e o arquivo novo continua no disco.
nada_comitado() {  # <vault>
  [ "$(git -C "$1" rev-list --count HEAD)" -eq 1 ] && [ -z "$(git -C "$1" diff --cached --name-only)" ] \
    && [ -f "$1/b.md" ]
}

# (c) gitleaks achou: tira do stage, não comita, lista os arquivos e sai 1. O docker roda sem rede e só leitura.
v="$(novo_vault achou)"
echo "chave $CHAVE_FALSA" >"$v/b.md"
rodar "$v" achou
args="$(cat "$LOG_DIR/docker-args" 2>/dev/null)"
if [ "$codigo" -eq 1 ] && nada_comitado "$v" \
  && grep -qx "vault-commit: ERRO: gitleaks achou segredo em: b.md, pasta/c d.md; nada foi comitado hoje." "$RAIZ/saida" \
  && printf '%s\n' "$args" | grep -qx -- "--network" && printf '%s\n' "$args" | grep -qx "none" \
  && printf '%s\n' "$args" | grep -qx "$v:/vault:ro" && printf '%s\n' "$args" | grep -qx -- "--redact" \
  && printf '%s\n' "$args" | grep -qx -- "--staged" \
  && printf '%s\n' "$args" | grep -q "^ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:[0-9a-f]\{64\}$"; then
  echo "ok gitleaks achou: nada comitado, stage limpo, arquivos no log"
else
  echo "FALHOU: gitleaks achou, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
fi

# (d) gitleaks falhou (imagem ausente, erro do docker): falha fechado.
v="$(novo_vault quebrado)"
echo "texto comum" >"$v/b.md"
rodar "$v" quebrado
if [ "$codigo" -eq 1 ] && nada_comitado "$v" && grep -q "ERRO: gitleaks não rodou (docker run saiu com 125" "$RAIZ/saida"; then
  echo "ok gitleaks que falha não deixa comitar"
else
  echo "FALHOU: gitleaks quebrado, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
fi

# (e) sem docker: falha fechado e diz por quê.
v="$(novo_vault sem-docker)"
echo "texto comum" >"$v/b.md"
rodar "$v" limpo "$SEM_DOCKER"
if [ "$codigo" -eq 1 ] && nada_comitado "$v" \
  && grep -qx "vault-commit: ERRO: docker não está disponível; o gitleaks não rodou; nada foi comitado hoje." "$RAIZ/saida"; then
  echo "ok sem docker não comita"
else
  echo "FALHOU: sem docker, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
fi

# (f) .gitleaksignore no vault (desligaria a varredura): recusa sem chamar o docker.
v="$(novo_vault ignora)"
echo "texto comum" >"$v/b.md"
echo "b.md:aws-access-token:1" >"$v/.gitleaksignore"
rm -f "$LOG_DIR/docker-args"
rodar "$v" limpo
if [ "$codigo" -eq 1 ] && nada_comitado "$v" && [ ! -e "$LOG_DIR/docker-args" ] \
  && grep -q "ERRO: o vault tem .gitleaksignore" "$RAIZ/saida"; then
  echo "ok .gitleaksignore no vault recusa"
else
  echo "FALHOU: .gitleaksignore, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
fi

# (g) limpo: comita e loga.
v="$(novo_vault limpo)"
echo "texto comum" >"$v/b.md"
rodar "$v" limpo
if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] \
  && grep -q "gitleaks: nada com cara de segredo." "$RAIZ/saida"; then
  echo "ok gitleaks limpo comita"
else
  echo "FALHOU: limpo, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
fi

# (h) imagem real do gitleaks (só com COM_DOCKER_REAL=1): pega a chave AWS falsa e deixa passar texto comum.
if [ "${COM_DOCKER_REAL:-0}" = "1" ]; then
  v="$(novo_vault real-achou)"
  echo "chave $CHAVE_FALSA" >"$v/b.md"
  PATH="$PATH" VAULT_PATH="$v" VAULT_PUSH=0 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 1 ] && nada_comitado "$v" \
    && grep -qx "vault-commit: ERRO: gitleaks achou segredo em: b.md; nada foi comitado hoje." "$RAIZ/saida" \
    && ! grep -q "$CHAVE_FALSA" "$RAIZ/saida" "$LOG_DIR/gitleaks.json" "$LOG_DIR/gitleaks.log"; then
    echo "ok imagem real: achou a chave AWS falsa, sem o valor no log nem no relatório"
  else
    echo "FALHOU: imagem real com chave, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
  fi
  v="$(novo_vault real-limpo)"
  echo "texto comum, senha do wifi em {{segredo:wifi}}" >"$v/b.md"
  PATH="$PATH" VAULT_PATH="$v" VAULT_PUSH=0 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ]; then
    echo "ok imagem real: texto comum comita"
  else
    echo "FALHOU: imagem real com texto comum, código $codigo"; cat "$RAIZ/saida"; falhas=$((falhas + 1))
  fi
fi

[ "$falhas" -eq 0 ] && echo "test_commit_diario: ok" || { echo "test_commit_diario: $falhas falha(s)"; exit 1; }
