#!/usr/bin/env bash
# Teste do commit diário do vault (deploy/vault/commit-diario.sh) num repositório temporário (sem vault real):
# config do repositório que rodaria comando não roda, o index.lock de um commit em andamento é esperado, e o
# gitleaks (com um `docker` falso) tira do commit só o arquivo com segredo, barra o push quando acha segredo nos
# commits, falha fechado quando quebra, passa do tempo ou não existe, e o relatório fica só com File, RuleID,
# StartLine e Commit, modo 600.
#   bash scripts/testes/test_commit_diario.sh
#   COM_DOCKER_REAL=1 bash scripts/testes/test_commit_diario.sh   # também roda a imagem real do gitleaks
set -u

SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault/commit-diario.sh"
CONFIG_GITLEAKS="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault/gitleaks.toml"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
falhas=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export LOG_DIR="$RAIZ/logs"
# Chave AWS inventada, montada em partes (scanner de repositório não acusa este arquivo).
CHAVE_FALSA="AKIA""Q3EGUJ7KZP2WXY5T"
# Chave de deploy falsa (o push só sai com ela); o ssh falso só confere o caminho. Espera curta entre os `git add`.
export VAULT_SSH_CHAVE="$RAIZ/chave deploy"
: >"$VAULT_SSH_CHAVE"
export VAULT_ADD_ESPERA=1
GIT_REAL="$(command -v git)"

# docker falso. `run`: grava os argumentos (docker-args-stage ou docker-args-commits) e age conforme
# $DOCKER_FALSO (varredura do stage) ou $DOCKER_FALSO_COMMITS (varredura dos commits): limpo, achou, quebrado, dorme.
# `achou` no stage lista os arquivos do stage com "AKIA" (nenhum: limpo); nos commits, c.md. `rm`: grava em docker-rm.
BIN_FALSO="$RAIZ/bin-falso"
mkdir -p "$BIN_FALSO"
cat >"$BIN_FALSO/docker" <<'FALSO'
#!/bin/bash
if [ "$1" = rm ]; then printf '%s\n' "$@" >>"$LOG_DIR/docker-rm"; exit 0; fi
vault="" relatorio="" tipo=commits anterior=""
for a in "$@"; do
  case "$anterior" in
    -v) case "$a" in *:/vault:ro) vault="${a%:/vault:ro}" ;; esac ;;
    --report-path) relatorio="$LOG_DIR/${a#/relatorio/}" ;;
  esac
  [ "$a" = --staged ] && tipo=stage
  anterior="$a"
done
printf '%s\n' "$@" >"$LOG_DIR/docker-args-$tipo"
if [ "$tipo" = stage ]; then modo="${DOCKER_FALSO:-limpo}"; else modo="${DOCKER_FALSO_COMMITS:-limpo}"; fi
case "$modo" in
  limpo) echo '[]' >"$relatorio"; exit 0 ;;
  # Limpo, e o servidor comita uma escrita no meio da varredura (o HEAD anda depois do commit varrido).
  limpo-e-comita)
    echo '[]' >"$relatorio"
    echo "escrita no meio" >>"$vault/00-inbox/meio.md"
    git -C "$vault" add 00-inbox/meio.md
    git -C "$vault" -c user.name=claude-app -c user.email=c@l -c commit.gpgsign=false commit -q -m meio
    exit 0 ;;
  achou)
    if [ "$tipo" = stage ]; then
      git -C "$vault" -c core.fsmonitor=false diff --cached --name-only -z \
        | while IFS= read -r -d '' f; do grep -q AKIA "$vault/$f" 2>/dev/null && printf '%s\0' "$f"; done >"$LOG_DIR/achados"
    else
      printf 'c.md\0' >"$LOG_DIR/achados"
    fi
    python3 -c '
import json, sys
achados = [a for a in open(sys.argv[2], encoding="utf-8").read().split("\0") if a]
json.dump([{"RuleID": "aws-access-token", "Match": "chave REDACTED contexto", "Secret": "REDACTED", "File": a,
            "StartLine": 1, "Commit": "", "Author": "Leonardo", "Email": "leo@x", "Message": "msg"} for a in achados],
          open(sys.argv[1], "w", encoding="utf-8"))' "$relatorio" "$LOG_DIR/achados"
    [ -s "$LOG_DIR/achados" ] && exit 3 || exit 0 ;;
  quebrado) echo "Unable to find image" >&2; exit 125 ;;
  dorme) exec sleep 30 ;;
esac
FALSO
chmod +x "$BIN_FALSO/docker"

# `timeout` de mentira (só no macOS, que não tem): mata o comando com TERM depois de N s e sai 124, como o GNU.
BIN_TIMEOUT="$RAIZ/bin-timeout"
mkdir -p "$BIN_TIMEOUT"
if ! command -v timeout >/dev/null 2>&1 && ! command -v gtimeout >/dev/null 2>&1; then
  cat >"$BIN_TIMEOUT/timeout" <<'FALSO'
#!/bin/bash
case "$1" in --kill-after=*) shift ;; esac
segundos="$1"; shift
"$@" & filho=$!
( sleep "$segundos"; kill -TERM "$filho" 2>/dev/null ) & vigia=$!
wait "$filho"; codigo=$?
if kill -0 "$vigia" 2>/dev/null; then kill "$vigia" 2>/dev/null; exit "$codigo"; fi
exit 124
FALSO
  chmod +x "$BIN_TIMEOUT/timeout"
fi
PATH_FALSO="$BIN_FALSO:$BIN_TIMEOUT:$PATH"

# ssh falso (push para remoto ssh://): grava os argumentos em ssh-args e roda o git receive-pack local no caminho
# pedido, como o sshd do GitHub faria. `-G` é a pergunta do git "é OpenSSH?": sim.
BIN_SSH="$RAIZ/bin-ssh"
mkdir -p "$BIN_SSH"
cat >"$BIN_SSH/ssh" <<'FALSO'
#!/bin/bash
printf '%s\n' "$@" >>"$LOG_DIR/ssh-args"
for a in "$@"; do [ "$a" = -G ] && exit 0; done
comando="${*: -1}"
case "$comando" in "git-receive-pack "*) exec sh -c "git receive-pack ${comando#git-receive-pack }" ;; esac
exit 1
FALSO
chmod +x "$BIN_SSH/ssh"
PATH_SSH="$BIN_SSH:$PATH_FALSO"

# git que cria um .git/index.lock no primeiro `git add` (o servidor comitando no meio) e o tira depois de 1 s
# (GIT_LOCK_SOME=1) ou nunca.
BIN_GIT_LOCK="$RAIZ/bin-git-lock"
mkdir -p "$BIN_GIT_LOCK"
cat >"$BIN_GIT_LOCK/git" <<FALSO
#!/bin/bash
for a in "\$@"; do
  if [ "\$a" = add ] && [ ! -e "\$LOG_DIR/lock-feito" ]; then
    : >"\$LOG_DIR/lock-feito"; : >.git/index.lock
    [ "\${GIT_LOCK_SOME:-1}" = 1 ] && ( sleep 1; rm -f .git/index.lock ) >/dev/null 2>&1 &
    break
  fi
done
exec "$GIT_REAL" "\$@"
FALSO
chmod +x "$BIN_GIT_LOCK/git"

# PATH só com o que o script usa, sem docker (link para cada comando).
COMANDOS="git date wc tr sleep mkdir rm id grep sed sort paste cat find python3 chmod dirname"
SEM_DOCKER="$RAIZ/bin-sem-docker"
mkdir -p "$SEM_DOCKER"
for c in $COMANDOS; do ln -s "$(command -v "$c")" "$SEM_DOCKER/$c"; done
# PATH com o docker falso e sem timeout nem gtimeout.
SEM_TIMEOUT="$RAIZ/bin-sem-timeout"
mkdir -p "$SEM_TIMEOUT"
for c in $COMANDOS; do ln -s "$(command -v "$c")" "$SEM_TIMEOUT/$c"; done
ln -s "$BIN_FALSO/docker" "$SEM_TIMEOUT/docker"

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
  printf '#!/bin/sh\n: > "%s"\ncat\n' "$RAIZ/marca-$1" >"$s"
  chmod +x "$s"
  echo "$s"
}

marcas() { ls "$RAIZ" | grep '^marca-' || true; }

# Roda o script com o docker falso no modo dado; deixa a saída em $RAIZ/saida e o código em $codigo.
rodar() {  # <vault> <modo do docker falso no stage> [PATH] [modo nos commits]
  rm -f "$LOG_DIR"/docker-args-* "$LOG_DIR/docker-rm"
  PATH="${3:-$PATH_FALSO}" DOCKER_FALSO="$2" DOCKER_FALSO_COMMITS="${4:-limpo}" VAULT_PATH="$1" \
    VAULT_PUSH="${VAULT_PUSH:-0}" "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
}

ok() { echo "ok $1"; }
falhou() { echo "FALHOU: $1"; cat "$RAIZ/saida"; falhas=$((falhas + 1)); }

# Não comitou, nada no stage e o arquivo novo continua no disco.
nada_comitado() {  # <vault>
  [ "$(git -C "$1" rev-list --count HEAD)" -eq 1 ] && [ -z "$(git -C "$1" diff --cached --name-only)" ] \
    && [ -f "$1/b.md" ]
}

modo_600() { [ "$(ls -l "$1" | cut -c1-10)" = "-rw-------" ]; }

# (a) ganchos, fsmonitor, sshCommand e gpg do repositório não rodam; o commit sai (sem assinatura).
v="$(novo_vault cfg)"
mkdir -p "$RAIZ/ganchos"
for g in pre-commit post-commit commit-msg; do cp "$(marca "$g")" "$RAIZ/ganchos/$g"; done
git -C "$v" config core.hooksPath "$RAIZ/ganchos"
git -C "$v" config core.fsmonitor "$(marca fsmonitor)"
git -C "$v" config core.sshCommand "$(marca ssh)"
git -C "$v" config commit.gpgsign true
git -C "$v" config gpg.program "$(marca gpg)"
git -C "$v" config filter.x.clean "$(marca filtro-sem-atributo)"
echo "mudou" >>"$v/00-inbox/a.md"
rodar "$v" limpo
n="$(git -C "$v" rev-list --count HEAD)"
if [ "$codigo" -eq 0 ] && [ "$n" -eq 2 ] && [ -z "$(marcas)" ]; then
  ok "config do repositório (ganchos, fsmonitor, ssh, gpg) não roda comando"
else
  falhou "config do repositório: código $codigo, $n commits, marcas: $(marcas)"
fi

# (a2) filtro declarado em .gitattributes (raiz, subpasta ou .git/info/attributes) com filter.x.clean na config:
# recusa antes de qualquer git que leia os arquivos; nenhuma marca, nada comitado, sem chamar o docker.
for onde in raiz subpasta info binario; do
  v="$(novo_vault "filtro-$onde")"
  git -C "$v" config filter.x.clean "$(marca "filtro-$onde")"
  git -C "$v" config commit.gpgsign true
  git -C "$v" config gpg.program "$(marca "gpg-$onde")"
  case "$onde" in
    raiz) echo '*.md filter=x' >"$v/.gitattributes" ;;
    subpasta) echo '*.md filter=x' >"$v/00-inbox/.gitattributes" ;;
    info) mkdir -p "$v/.git/info"; echo '*.md filter=x' >"$v/.git/info/attributes" ;;
    binario) echo '*.md binary' >"$v/00-inbox/.gitattributes" ;;
  esac
  echo "texto comum" >"$v/b.md"
  rodar "$v" limpo
  if [ "$codigo" -eq 1 ] && nada_comitado "$v" && [ -z "$(marcas)" ] && [ ! -e "$LOG_DIR/docker-args-stage" ] \
    && grep -q "ERRO: o vault tem .*attributes com filter, diff ou binary" "$RAIZ/saida"; then
    ok "filtro em .gitattributes ($onde): recusa sem rodar comando"
  else
    falhou "filtro em .gitattributes ($onde): código $codigo, marcas: $(marcas)"
  fi
done

# (a3) .gitattributes com comentário que cita "diff" (como o do vault real) e `text eol`: não recusa. Atributo de
# verdade (diff=x, -diff, binary, filter, macro [attr]) recusa.
v="$(novo_vault attr-comentario)"
printf '%s\n' '# Sem isto, cada troca de maquina gera' '# diff de arquivo inteiro (binary, filter).' '* text=auto eol=lf' \
  >"$v/.gitattributes"
echo "texto comum" >"$v/b.md"
rodar "$v" limpo
if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] && ! grep -q "ERRO" "$RAIZ/saida"; then
  ok ".gitattributes com comentário sobre diff: comita"
else
  falhou ".gitattributes com comentário, código $codigo"
fi
for linha in '*.md diff=x' '*.md -diff' '  *.md   binary' '*.md !filter' '[attr]meu filter=x'; do
  v="$(novo_vault attr-recusa)"
  printf '%s\n' '# comentário' "$linha" >"$v/.gitattributes"
  echo "texto comum" >"$v/b.md"
  rodar "$v" limpo
  if [ "$codigo" -eq 1 ] && nada_comitado "$v" && grep -q "ERRO: o vault tem .gitattributes com filter, diff ou binary" "$RAIZ/saida"; then
    ok ".gitattributes com [$linha]: recusa"
  else
    falhou ".gitattributes com [$linha], código $codigo"
  fi
  rm -rf "$v"
done

# (b) index.lock de um commit em andamento: espera ele sair e comita.
v="$(novo_vault lock)"
echo "mudou" >>"$v/00-inbox/a.md"
: >"$v/.git/index.lock"
( sleep 2; rm -f "$v/.git/index.lock" ) &
rodar "$v" limpo
wait
n="$(git -C "$v" rev-list --count HEAD)"
if [ "$codigo" -eq 0 ] && [ "$n" -eq 2 ]; then
  ok "espera o index.lock e comita"
else
  falhou "com index.lock temporário, código $codigo e $n commits"
fi

# (b2) index.lock que aparece no meio do `git add` (o servidor comitou depois da espera) e some: tenta de novo e comita.
v="$(novo_vault lock-no-add)"
echo "mudou" >>"$v/00-inbox/a.md"
rm -f "$LOG_DIR/lock-feito"
GIT_LOCK_SOME=1 rodar "$v" limpo "$BIN_GIT_LOCK:$PATH_FALSO"
wait
if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] && [ -e "$LOG_DIR/lock-feito" ] \
  && grep -q "index.lock ocupado no git add" "$RAIZ/saida"; then
  ok "index.lock no meio do git add: tenta de novo e comita"
else
  falhou "index.lock no git add, código $codigo"
fi
# O lock não some: 3 tentativas e ERRO, nada comitado.
v="$(novo_vault lock-preso)"
echo "texto comum" >"$v/b.md"
rm -f "$LOG_DIR/lock-feito"
GIT_LOCK_SOME=0 rodar "$v" limpo "$BIN_GIT_LOCK:$PATH_FALSO"
rm -f "$v/.git/index.lock"
if [ "$codigo" -eq 1 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 1 ] \
  && [ "$(grep -c "index.lock ocupado no git add" "$RAIZ/saida")" -eq 2 ] && grep -q "ERRO: git add falhou" "$RAIZ/saida"; then
  ok "index.lock preso no git add: 3 tentativas e ERRO"
else
  falhou "index.lock preso no git add, código $codigo"
fi

# (c) gitleaks achou em dois arquivos: só eles saem do stage, o resto é comitado, ERRO com os arquivos e saída 1.
# O docker roda sem rede, só leitura, com a config do repositório; o relatório fica só com 4 campos, modo 600.
v="$(novo_vault achou)"
echo "mudou" >>"$v/00-inbox/a.md"
echo "chave $CHAVE_FALSA" >"$v/b.md"
mkdir -p "$v/pasta"
echo "outra $CHAVE_FALSA" >"$v/pasta/c d.md"
rodar "$v" achou
args="$(cat "$LOG_DIR/docker-args-stage" 2>/dev/null)"
comitados="$(git -C "$v" show --name-only --format= HEAD | sort | paste -sd ',' -)"
campos="$(python3 -c 'import json,sys; print(sorted({k for a in json.load(open(sys.argv[1])) for k in a}))' "$LOG_DIR/gitleaks.json" 2>&1)"
if [ "$codigo" -eq 1 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] && [ "$comitados" = "00-inbox/a.md" ] \
  && [ -f "$v/b.md" ] && [ -f "$v/pasta/c d.md" ] && [ -z "$(git -C "$v" diff --cached --name-only)" ] \
  && grep -qF "vault-commit: ERRO: gitleaks achou segredo em: b.md, pasta/c d.md; esses arquivos ficaram fora do commit de hoje" "$RAIZ/saida" \
  && grep -qx "vault-commit: commit feito em $(date +%F): 1 arquivos." "$RAIZ/saida" \
  && [ "$campos" = "['Commit', 'File', 'RuleID', 'StartLine']" ] && ! grep -q "contexto" "$LOG_DIR/gitleaks.json" \
  && modo_600 "$LOG_DIR/gitleaks.json" && modo_600 "$LOG_DIR/gitleaks.log" \
  && printf '%s\n' "$args" | grep -qx -- "--network" && printf '%s\n' "$args" | grep -qx "none" \
  && printf '%s\n' "$args" | grep -qx "$v:/vault:ro" && printf '%s\n' "$args" | grep -qx -- "--redact" \
  && printf '%s\n' "$args" | grep -qx -- "--staged" \
  && printf '%s\n' "$args" | grep -qx "$CONFIG_GITLEAKS:/config/gitleaks.toml:ro" \
  && printf '%s\n' "$args" | grep -qx -- "--config" && printf '%s\n' "$args" | grep -qx "/config/gitleaks.toml" \
  && printf '%s\n' "$args" | grep -q "^assistente-gitleaks-[0-9]*-stage$" \
  && printf '%s\n' "$args" | grep -q "^ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:[0-9a-f]\{64\}$"; then
  ok "gitleaks achou: só os arquivos do relatório saem do stage, o resto comita; relatório com 4 campos, modo 600"
else
  falhou "gitleaks achou, código $codigo, comitados [$comitados], campos $campos"
fi

# (c2) só arquivo com segredo mudou: nada sobra para comitar, ERRO e saída 1.
v="$(novo_vault so-segredo)"
echo "chave $CHAVE_FALSA" >"$v/b.md"
rodar "$v" achou
if [ "$codigo" -eq 1 ] && nada_comitado "$v" && grep -q "nada sobrou para comitar" "$RAIZ/saida" \
  && grep -q "ERRO: gitleaks achou segredo em: b.md;" "$RAIZ/saida"; then
  ok "só o arquivo com segredo mudou: nada comitado"
else
  falhou "só segredo, código $codigo"
fi

# (d) gitleaks falhou (imagem ausente, erro do docker): falha fechado, sem carimbo de execução limpa.
v="$(novo_vault quebrado)"
echo "texto comum" >"$v/b.md"
rm -f "$LOG_DIR/ultima-execucao-ok"
rodar "$v" quebrado
if [ "$codigo" -eq 1 ] && nada_comitado "$v" && grep -q "ERRO: gitleaks não rodou (docker run saiu com 125" "$RAIZ/saida" \
  && [ ! -e "$LOG_DIR/ultima-execucao-ok" ]; then
  ok "gitleaks que falha não deixa comitar"
else
  falhou "gitleaks quebrado, código $codigo"
fi

# (e) sem docker: falha fechado e diz por quê.
v="$(novo_vault sem-docker)"
echo "texto comum" >"$v/b.md"
rodar "$v" limpo "$SEM_DOCKER"
if [ "$codigo" -eq 1 ] && nada_comitado "$v" \
  && grep -qx "vault-commit: ERRO: docker não está disponível; o gitleaks não rodou; nada foi comitado hoje." "$RAIZ/saida"; then
  ok "sem docker não comita"
else
  falhou "sem docker, código $codigo"
fi

# (f) .gitleaksignore no vault, ou .gitleaks.toml como link pendurado (desligariam a varredura): recusa sem docker.
for caso in ignora link; do
  v="$(novo_vault "f-$caso")"
  echo "texto comum" >"$v/b.md"
  if [ "$caso" = ignora ]; then
    echo "b.md:aws-access-token:1" >"$v/.gitleaksignore"; nome=.gitleaksignore
  else
    ln -s /vault/.obsidian/nao-existe.toml "$v/.gitleaks.toml"; nome=.gitleaks.toml
  fi
  rodar "$v" limpo
  if [ "$codigo" -eq 1 ] && nada_comitado "$v" && [ ! -e "$LOG_DIR/docker-args-stage" ] \
    && grep -q "ERRO: o vault tem $nome" "$RAIZ/saida"; then
    ok "$nome no vault ($caso) recusa"
  else
    falhou "$nome ($caso), código $codigo"
  fi
done

# (f2) Pastas do Syncthing: ficam fora do commit com ou sem linha no .gitignore do vault, e o add não falha
# quando o .gitignore já as ignora (o git recusava o pathspec `:!.stfolder` de caminho ignorado; i7, 2026-10-23).
for com_gitignore in sim nao; do
  v="$(novo_vault "syncthing-$com_gitignore")"
  [ "$com_gitignore" = sim ] && printf '.stfolder/\n.stversions/\n' >"$v/.gitignore"
  mkdir -p "$v/.stfolder" "$v/.stversions" "$v/.git-mac-parado"
  : >"$v/.stfolder/marca"; : >"$v/.stversions/a~20261023.md"; : >"$v/.git-mac-parado/HEAD"
  : >"$v/00-inbox/.syncthing.a.md.tmp"; : >"$v/00-inbox/x.syncthing.1.tmp"
  echo "texto comum" >"$v/b.md"
  rodar "$v" limpo
  rastreados="$(git -C "$v" ls-files)"
  if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] && printf '%s\n' "$rastreados" | grep -qx b.md \
    && ! printf '%s\n' "$rastreados" | grep -qE '^\.stfolder/|^\.stversions/|^\.git-mac-parado/|\.syncthing\..*\.tmp$'; then
    ok "pastas do Syncthing fora do commit (.gitignore com elas: $com_gitignore)"
  else
    falhou "pastas do Syncthing (.gitignore com elas: $com_gitignore), código $codigo"
  fi
done

# (g) limpo: comita, varre o histórico inteiro na primeira vez e guarda o último commit varrido; na segunda, sem
# commit novo, não varre; depois de um commit por escrita (outro autor), varre só o intervalo novo.
v="$(novo_vault limpo)"
echo "texto comum" >"$v/b.md"
rm -f "$LOG_DIR/ultimo-varrido"
rodar "$v" limpo
topo="$(git -C "$v" rev-parse HEAD)"
args_c="$(cat "$LOG_DIR/docker-args-commits" 2>/dev/null)"
if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] \
  && grep -q "gitleaks: nada com cara de segredo no stage." "$RAIZ/saida" \
  && grep -q "varro o histórico inteiro" "$RAIZ/saida" && ! printf '%s\n' "$args_c" | grep -qx -- "--log-opts" \
  && [ "$(cat "$LOG_DIR/ultimo-varrido")" = "$topo" ] && modo_600 "$LOG_DIR/ultimo-varrido" \
  && [ "$(ls -l "$LOG_DIR/ultima-execucao-ok" | cut -c1-10)" = "-rw-r--r--" ] \
  && grep -qx '[0-9]*' "$LOG_DIR/ultima-execucao-ok"; then
  ok "limpo comita; primeira varredura dos commits pega o histórico inteiro; carimbo de execução limpa, modo 644"
else
  falhou "limpo, código $codigo"
fi
echo 1 >"$LOG_DIR/ultima-execucao-ok"
rodar "$v" limpo
if [ "$codigo" -eq 0 ] && grep -q "nenhum commit novo desde a última varredura" "$RAIZ/saida" \
  && [ ! -e "$LOG_DIR/docker-args-commits" ] && [ "$(cat "$LOG_DIR/ultima-execucao-ok")" -gt 1 ]; then
  ok "sem commit novo, não varre de novo; sem mudança também grava o carimbo"
else
  falhou "sem commit novo, código $codigo"
fi
echo "escrita da IA" >"$v/00-inbox/ia.md"
git -C "$v" add -A && git -C "$v" -c user.name=claude-app -c user.email=c@l -c commit.gpgsign=false commit -q -m ia
novo="$(git -C "$v" rev-parse HEAD)"
rodar "$v" limpo
args_c="$(cat "$LOG_DIR/docker-args-commits" 2>/dev/null)"
if [ "$codigo" -eq 0 ] && printf '%s\n' "$args_c" | grep -qx -- "--log-opts" \
  && printf '%s\n' "$args_c" | grep -qx "$topo..$novo" && [ "$(cat "$LOG_DIR/ultimo-varrido")" = "$novo" ]; then
  ok "commit por escrita: varre só o intervalo desde a última varredura"
else
  falhou "intervalo dos commits, código $codigo, args: $args_c"
fi

# (h) segredo num commit por escrita (passou sem o gitleaks): ERRO com o arquivo, sem push, saída 1, e o último
# varrido não anda. Com o commit limpo e VAULT_PUSH=1, o push é tentado (o remoto de pasta local é recusado: só ssh).
v="$(novo_vault commits)"
git -C "$v" init -q --bare "$RAIZ/remoto-commits.git"
git -C "$v" remote add origin "$RAIZ/remoto-commits.git"
rm -f "$LOG_DIR/ultimo-varrido"
VAULT_PUSH=1 rodar "$v" limpo "" achou
if [ "$codigo" -eq 1 ] && grep -q "ERRO: gitleaks achou segredo em commits já feitos, nos arquivos: c.md; sem push." "$RAIZ/saida" \
  && ! grep -q "push" <(grep -v "sem push" "$RAIZ/saida") && [ ! -e "$LOG_DIR/ultimo-varrido" ] \
  && modo_600 "$LOG_DIR/gitleaks-commits.json"; then
  ok "segredo nos commits: sem push e sem andar o último varrido"
else
  falhou "segredo nos commits, código $codigo"
fi
VAULT_PUSH=1 rodar "$v" limpo "" quebrado
if [ "$codigo" -eq 1 ] && grep -q "ERRO: gitleaks não rodou (docker run saiu com 125.* nos commits; sem push." "$RAIZ/saida" \
  && ! grep -q "git push" "$RAIZ/saida"; then
  ok "varredura dos commits que falha: sem push"
else
  falhou "varredura dos commits quebrada, código $codigo"
fi
VAULT_PUSH=1 rodar "$v" limpo
if [ "$codigo" -eq 1 ] && grep -q "ERRO: git push falhou" "$RAIZ/saida" \
  && [ -z "$(git -C "$RAIZ/remoto-commits.git" rev-list --all)" ]; then
  ok "commits limpos: push tentado, e remoto de pasta local recusado (só ssh)"
else
  falhou "push com commits limpos, código $codigo"
fi

# (h2) push por ssh: leva a chave de deploy (-i, IdentitiesOnly, BatchMode) e manda o commit VARRIDO para a branch
# atual, não o HEAD (o servidor comitou no meio da varredura).
v="$(novo_vault push-ssh)"
git -C "$v" init -q --bare "$RAIZ/remoto-ssh.git"
git -C "$v" remote add origin "ssh://i7-falso$RAIZ/remoto-ssh.git"
git -C "$v" checkout -q -b principal
echo "texto comum" >"$v/b.md"
rm -f "$LOG_DIR/ultimo-varrido" "$LOG_DIR/ssh-args"
VAULT_PUSH=1 rodar "$v" limpo "$PATH_SSH" limpo-e-comita
varrido="$(cat "$LOG_DIR/ultimo-varrido" 2>/dev/null)"
remoto="$(git -C "$RAIZ/remoto-ssh.git" rev-parse -q --verify refs/heads/principal)"
ssh_args="$(cat "$LOG_DIR/ssh-args" 2>/dev/null)"
if [ "$codigo" -eq 0 ] && grep -q "push feito" "$RAIZ/saida" && [ -n "$varrido" ] && [ "$remoto" = "$varrido" ] \
  && [ "$(git -C "$v" rev-parse HEAD)" != "$varrido" ] \
  && printf '%s\n' "$ssh_args" | grep -qx -- "-i" && printf '%s\n' "$ssh_args" | grep -qxF "$VAULT_SSH_CHAVE" \
  && printf '%s\n' "$ssh_args" | grep -qx "IdentitiesOnly=yes" && printf '%s\n' "$ssh_args" | grep -qx "BatchMode=yes"; then
  ok "push por ssh com a chave de deploy, do commit varrido para a branch atual"
else
  falhou "push por ssh, código $codigo, varrido $varrido, remoto $remoto, ssh: $(printf '%s ' $ssh_args)"
fi
# Sem a chave: ERRO claro, nenhum push (o ssh nem roda) e o carimbo de execução limpa não anda.
echo "outra" >"$v/c.md"
rm -f "$LOG_DIR/ssh-args"
echo 1 >"$LOG_DIR/ultima-execucao-ok"
VAULT_SSH_CHAVE="$RAIZ/nao-existe" VAULT_PUSH=1 rodar "$v" limpo "$PATH_SSH"
if [ "$codigo" -eq 1 ] && grep -q "ERRO: não achei a chave de deploy em $RAIZ/nao-existe" "$RAIZ/saida" \
  && [ ! -e "$LOG_DIR/ssh-args" ] && [ "$(git -C "$RAIZ/remoto-ssh.git" rev-parse refs/heads/principal)" = "$remoto" ] \
  && [ "$(cat "$LOG_DIR/ultima-execucao-ok")" = 1 ]; then
  ok "sem a chave de deploy: ERRO e sem push"
else
  falhou "sem a chave de deploy, código $codigo"
fi
# HEAD solto (fora de branch): ERRO e sem push.
git -C "$v" checkout -q --detach
rm -f "$LOG_DIR/ssh-args"
VAULT_PUSH=1 rodar "$v" limpo "$PATH_SSH"
if [ "$codigo" -eq 1 ] && grep -q "ERRO: HEAD solto" "$RAIZ/saida" && [ ! -e "$LOG_DIR/ssh-args" ]; then
  ok "HEAD solto: ERRO e sem push"
else
  falhou "HEAD solto, código $codigo"
fi

# (i) gitleaks que não termina: parado em GITLEAKS_TIMEOUT s, container removido, nada comitado.
v="$(novo_vault dorme)"
echo "texto comum" >"$v/b.md"
inicio=$(date +%s)
GITLEAKS_TIMEOUT=2 rodar "$v" dorme
gasto=$(( $(date +%s) - inicio ))
if [ "$codigo" -eq 1 ] && nada_comitado "$v" && [ "$gasto" -lt 20 ] \
  && grep -q "ERRO: gitleaks passou de 2 s e foi parado; nada foi comitado hoje." "$RAIZ/saida" \
  && grep -q "^assistente-gitleaks-[0-9]*-stage$" "$LOG_DIR/docker-rm"; then
  ok "gitleaks parado no tempo (${gasto} s) e container removido"
else
  falhou "timeout, código $codigo, ${gasto} s"
fi

# (j) sem timeout nem gtimeout: roda sem limite e avisa.
v="$(novo_vault sem-timeout)"
echo "texto comum" >"$v/b.md"
rodar "$v" limpo "$SEM_TIMEOUT"
if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] \
  && grep -q "AVISO: sem timeout nem gtimeout" "$RAIZ/saida"; then
  ok "sem timeout: comita e avisa"
else
  falhou "sem timeout, código $codigo"
fi

# (k) imagem real do gitleaks (só com COM_DOCKER_REAL=1): pega a chave AWS falsa no stage e num commit por escrita,
# deixa passar texto comum, e nem o relatório nem o log têm o valor ou o contexto (`Match`).
if [ "${COM_DOCKER_REAL:-0}" = "1" ]; then
  REAL="$BIN_TIMEOUT:$PATH"
  v="$(novo_vault real-achou)"
  echo "mudou" >>"$v/00-inbox/a.md"
  echo "chave $CHAVE_FALSA" >"$v/b.md"
  rm -f "$LOG_DIR/ultimo-varrido"
  PATH="$REAL" VAULT_PATH="$v" VAULT_PUSH=0 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 1 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] && [ -f "$v/b.md" ] \
    && grep -q "vault-commit: ERRO: gitleaks achou segredo em: b.md; esses arquivos ficaram fora" "$RAIZ/saida" \
    && ! grep -q "$CHAVE_FALSA" "$RAIZ/saida" "$LOG_DIR/gitleaks.json" "$LOG_DIR/gitleaks.log" \
    && ! grep -q '"Match"' "$LOG_DIR/gitleaks.json"; then
    ok "imagem real: achou a chave AWS falsa, comitou o resto, sem o valor no log nem no relatório"
  else
    falhou "imagem real com chave, código $codigo"
  fi
  # Commit por escrita com a chave (antes da barreira): o commit diário acha e não faz push.
  echo "chave $CHAVE_FALSA" >"$v/00-inbox/ia.md"
  git -C "$v" add 00-inbox/ia.md
  git -C "$v" -c user.name=claude-app -c user.email=c@l -c commit.gpgsign=false commit -q -m ia
  rm -f "$v/b.md"
  PATH="$REAL" VAULT_PATH="$v" VAULT_PUSH=1 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 1 ] && grep -q "ERRO: gitleaks achou segredo em commits já feitos, nos arquivos: 00-inbox/ia.md; sem push." "$RAIZ/saida" \
    && ! grep -q "$CHAVE_FALSA" "$RAIZ/saida" "$LOG_DIR/gitleaks-commits.json" "$LOG_DIR/gitleaks-commits.log"; then
    ok "imagem real: segredo num commit por escrita barra o push"
  else
    falhou "imagem real com segredo no commit, código $codigo"
  fi
  v="$(novo_vault real-limpo)"
  echo "texto comum, senha do wifi em {{segredo:wifi}}" >"$v/b.md"
  rm -f "$LOG_DIR/ultimo-varrido"
  PATH="$REAL" VAULT_PATH="$v" VAULT_PUSH=0 "$BASH" "$SCRIPT" >"$RAIZ/saida" 2>&1
  codigo=$?
  if [ "$codigo" -eq 0 ] && [ "$(git -C "$v" rev-list --count HEAD)" -eq 2 ] \
    && [ "$(cat "$LOG_DIR/ultimo-varrido")" = "$(git -C "$v" rev-parse HEAD)" ]; then
    ok "imagem real: texto comum comita e os commits saem limpos"
  else
    falhou "imagem real com texto comum, código $codigo"
  fi
fi

[ "$falhas" -eq 0 ] && echo "test_commit_diario: ok" || { echo "test_commit_diario: $falhas falha(s)"; exit 1; }
