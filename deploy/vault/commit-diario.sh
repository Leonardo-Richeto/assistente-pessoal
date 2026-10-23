#!/usr/bin/env bash
# Commit diário do vault (histórico de tudo que a IA e o Leonardo escreveram).
# Só comita se houver mudança. Só faz push se VAULT_PUSH=1 e a varredura dos commits saiu limpa. Não apaga nada.
#
# gitleaks (imagem Docker com versão e digest fixos, sem rede, vault só leitura, config do repositório do app com
# `--config`, limite de GITLEAKS_TIMEOUT segundos) roda duas vezes:
#   1. No que está no stage. Achou: tira do stage só os arquivos do relatório (`git reset`, o disco não muda),
#      confere o resto de novo e comita o resto; loga ERRO com os arquivos. Não rodou: tira tudo do stage e não comita.
#   2. Nos commits desde a última varredura limpa (commits por escrita do servidor, fotos e o commit de hoje). O id
#      do último commit varrido fica em $LOG_DIR/ultimo-varrido, fora do vault (o container do servidor escreve no
#      .git). Primeira vez, ou id que não é ancestral do HEAD: o histórico inteiro. Achou ou não rodou: ERRO com os
#      arquivos e sem push (nada é apagado; reescrever o histórico fica com o dono).
# Saída 1 se houve qualquer ERRO (o systemd marca o serviço como falho). Relatórios só com File, RuleID, StartLine e
# Commit (o `Match` do gitleaks tem contexto mesmo com --redact), em LOG_DIR, modo 600.
# Execução sem ERRO (com ou sem mudança) grava a hora em $LOG_DIR/ultima-execucao-ok (modo 644): o lint diário avisa
# quando ela passa de 2 dias.
# Push (VAULT_PUSH=1): do commit varrido (não do HEAD, que pode ter andado no meio) para a branch atual no `origin`,
# por ssh com a chave de deploy (VAULT_SSH_CHAVE, padrão ~/.ssh/vault_deploy). Sem a chave: ERRO e sem push.
# Chamado pelo vault-commit.service; também roda à mão:
#   VAULT_PATH=/srv/assistente/vault bash deploy/vault/commit-diario.sh
# Saída vai para o journal: journalctl -u vault-commit.service
set -u

VAULT_PATH="${VAULT_PATH:-/srv/assistente/vault}"
VAULT_PUSH="${VAULT_PUSH:-0}"
LOG_DIR="${LOG_DIR:-/srv/assistente/logs/vault-commit}"
PASTA_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GITLEAKS_CONFIG="${GITLEAKS_CONFIG:-$PASTA_SCRIPT/gitleaks.toml}"
# gitleaks v8.30.1 (2026-03-21). Digest do índice multi-arquitetura (amd64 e arm64), conferido com
# `docker buildx imagetools inspect` em 2026-10-22. Para atualizar: leia o changelog, troque os dois juntos.
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f}"
GITLEAKS_ACHOU=3  # código de saída do gitleaks quando acha segredo; qualquer outro diferente de 0 é falha dele
GITLEAKS_TIMEOUT="${GITLEAKS_TIMEOUT:-900}"  # segundos por varredura; o vault-commit.service para tudo em 30 min
AUTOR_DIARIO="Vault (commit diário)"
CONTEINER="assistente-gitleaks-$$"
ULTIMO_VARRIDO="$LOG_DIR/ultimo-varrido"
CARIMBO="$LOG_DIR/ultima-execucao-ok"  # o lint-diario.sh lê (CARIMBO_COMMIT)
CHAVE_SSH="${VAULT_SSH_CHAVE:-${HOME:-}/.ssh/vault_deploy}"
ESPERA_ADD="${VAULT_ADD_ESPERA:-2}"  # segundos entre as tentativas do git add com index.lock ocupado
TOPO_VARRIDO=""  # commit que a varredura dos commits viu limpo; o push manda este, não o HEAD
ERROS=0

log() { echo "vault-commit: $*"; }
erro() { log "ERRO: $*"; ERROS=1; }

# Container que ficou para trás (timeout mata o `docker run`, não o container): remove ao sair.
trap 'command -v docker >/dev/null 2>&1 && docker rm -f "$CONTEINER-stage" "$CONTEINER-commits" >/dev/null 2>&1; rm -f "$IGNORAR_SEMPRE"' EXIT

# Fora do commit mesmo sem linha no .gitignore do vault: o que o Syncthing deixa na pasta e um .git guardado por
# engano. Vai por core.excludesFile, não por pathspec `:!`: o git recusa o add inteiro quando um pathspec nomeia um
# caminho que o .gitignore já ignora ("paths are ignored", visto no i7 em 2026-10-23 com o .stfolder).
IGNORAR_SEMPRE="$(mktemp)"
printf '%s\n' '/.stversions' '/.stfolder' '*.syncthing.*.tmp' '/.git-mac-parado' >"$IGNORAR_SEMPRE"

[ -d "$VAULT_PATH/.git" ] || { log "ERRO: $VAULT_PATH não é um repositório git."; exit 1; }
cd "$VAULT_PATH" || exit 1

# Config do repositório que rodaria comando (ganchos, fsmonitor, ssh, gpg, filtros) não vale aqui: o .git fica na
# pasta que o container também escreve. Nome e e-mail só para este commit; não altera a config do repositório.
# `filter.<x>.clean` não dá para neutralizar sem saber o nome: o vault com .gitattributes que declara filtro é
# recusado antes de qualquer comando git que leia os arquivos (recusa_do_vault).
SEGURO=(-c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.sshCommand=false -c commit.gpgsign=false
  -c gpg.program=false -c core.attributesFile=/dev/null -c diff.external= -c log.showSignature=false
  -c core.pager=cat)
GIT=(git "${SEGURO[@]}" -c user.name="$AUTOR_DIARIO" -c user.email="vault@localhost")

# O servidor pode estar comitando uma escrita da IA: espera o index.lock sair (até 60 s, de 5 em 5).
ESPERA=0
while [ -e .git/index.lock ] && [ "$ESPERA" -lt 60 ]; do
  sleep 5
  ESPERA=$((ESPERA + 5))
done
[ -e .git/index.lock ] && { log "ERRO: .git/index.lock ocupado há mais de 60 s; nada comitado (o lint diário avisa)."; exit 1; }

# Motivo para recusar o vault inteiro hoje (imprime e sai 0), ou nada (sai 1).
recusa_do_vault() {
  local f
  # Config e lista de ignorados do gitleaks vindas do vault (Syncthing) desligariam a varredura. Link simbólico
  # (mesmo pendurado) também: o gitleaks seguiria o link de dentro do container.
  for f in .gitleaks.toml .gitleaksignore; do
    if [ -e "$f" ] || [ -L "$f" ]; then
      echo "o vault tem $f (desligaria regras do gitleaks); tire o arquivo"; return 0
    fi
  done
  # .gitattributes com filter (o `git add` e o `git status` rodariam o comando do filtro), diff (textconv roda
  # comando) ou binary (esconderia o conteúdo do gitleaks), em qualquer pasta, ou em .git/info/attributes.
  local lista
  lista="$(find . -path ./.git -prune -o -name .gitattributes -print 2>/dev/null; echo ./.git/info/attributes)"
  # Linha de comentário (`#`, com ou sem espaço antes) não conta; o atributo, com `-` ou `!` antes ou `=valor` depois,
  # conta em qualquer posição depois do padrão (inclusive numa macro `[attr]x filter=y`).
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ -L "$f" ] || { [ -f "$f" ] && grep -vE '^[[:space:]]*#' "$f" \
      | grep -qiE '(^|[[:space:]])[-!]?(filter|diff|binary)(=|[[:space:]]|$)'; }; then
      echo "o vault tem ${f#./} com filter, diff ou binary (rodaria comando ou esconderia conteúdo do gitleaks); tire a linha"
      return 0
    fi
  done <<<"$lista"
  return 1
}

# Tira tudo do stage (o disco fica igual: nada se perde) e diz por que não comitou.
nao_comitar() {  # <motivo>
  "${GIT[@]}" reset -q || log "ERRO: git reset falhou; o stage ficou com as mudanças de hoje."
  erro "$1; nada foi comitado hoje."
}

# Comando que limita o tempo do docker run. Sem `timeout` (macOS dos testes) nem `gtimeout`, roda sem limite e avisa.
LIMITE=()
if command -v timeout >/dev/null 2>&1; then
  LIMITE=(timeout --kill-after=30 "$GITLEAKS_TIMEOUT")
elif command -v gtimeout >/dev/null 2>&1; then
  LIMITE=(gtimeout --kill-after=30 "$GITLEAKS_TIMEOUT")
fi

# Antes de rodar o gitleaks: docker, config e pasta do relatório. Imprime o motivo se falta algo.
falta_para_o_gitleaks() {
  if ! command -v docker >/dev/null 2>&1; then echo "docker não está disponível; o gitleaks não rodou"; return 0; fi
  if [ ! -f "$GITLEAKS_CONFIG" ]; then echo "não achei a config do gitleaks em $GITLEAKS_CONFIG; o gitleaks não rodou"; return 0; fi
  if ! mkdir -p "$LOG_DIR" 2>/dev/null || [ ! -w "$LOG_DIR" ]; then
    echo "não consigo escrever o relatório em $LOG_DIR; o gitleaks não rodou"; return 0
  fi
  return 1
}

# Roda o gitleaks. <nome do container> <relatório> <log> [argumentos do modo git...]. Devolve o código do gitleaks
# (124 ou 137: passou do tempo).
rodar_gitleaks() {
  local nome="$1" relatorio="$2" saida="$3"
  shift 3
  rm -f "$relatorio"
  : >"$saida"
  chmod 600 "$saida"
  if [ "${#LIMITE[@]}" -eq 0 ]; then
    log "AVISO: sem timeout nem gtimeout; o gitleaks roda sem limite de tempo (o systemd para em 30 min)."
  fi
  # Sem rede, só leitura, sem privilégio, com o uid do dono do vault. O git de dentro da imagem não usa ganchos,
  # fsmonitor, diff externo nem attributesFile do repositório (GIT_CONFIG_* vale como `-c`). `gitleaks:allow` na nota
  # não vale. A config vem do repositório do app (--config vence a da raiz do vault).
  ${LIMITE[@]+"${LIMITE[@]}"} docker run --rm --name "$CONTEINER-$nome" --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    -v "$VAULT_PATH:/vault:ro" -v "$LOG_DIR:/relatorio" -v "$GITLEAKS_CONFIG:/config/gitleaks.toml:ro" \
    -e GIT_CONFIG_COUNT=6 \
    -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/vault \
    -e GIT_CONFIG_KEY_1=core.hooksPath -e GIT_CONFIG_VALUE_1=/dev/null \
    -e GIT_CONFIG_KEY_2=core.fsmonitor -e GIT_CONFIG_VALUE_2=false \
    -e GIT_CONFIG_KEY_3=diff.external -e GIT_CONFIG_VALUE_3= \
    -e GIT_CONFIG_KEY_4=core.sshCommand -e GIT_CONFIG_VALUE_4=false \
    -e GIT_CONFIG_KEY_5=core.attributesFile -e GIT_CONFIG_VALUE_5=/dev/null \
    "$GITLEAKS_IMAGE" git "$@" --config /config/gitleaks.toml --redact --no-banner --no-color \
    --ignore-gitleaks-allow --gitleaks-ignore-path /nao-existe --exit-code "$GITLEAKS_ACHOU" \
    --report-format json --report-path "/relatorio/${relatorio##*/}" /vault >"$saida" 2>&1
}

# Reescreve o relatório só com File, RuleID, StartLine e Commit (modo 600) e grava em <lista> os arquivos achados,
# separados por NUL. Sai diferente de 0 se o relatório não existe ou não é a lista JSON do gitleaks.
resumir_relatorio() {  # <relatorio> <lista>
  python3 -I -c '
import json, os, sys
relatorio, lista = sys.argv[1], sys.argv[2]
with open(relatorio, encoding="utf-8") as f:
    achados = json.load(f)
if not isinstance(achados, list) or not all(isinstance(a, dict) for a in achados):
    sys.exit(2)
limpo = [{k: a.get(k) for k in ("File", "RuleID", "StartLine", "Commit")} for a in achados]
with open(relatorio, "w", encoding="utf-8") as f:
    json.dump(limpo, f, ensure_ascii=False, indent=1)
os.chmod(relatorio, 0o600)
arquivos = sorted({str(a["File"]) for a in limpo if a.get("File")})
with open(lista, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write("".join(a + "\0" for a in arquivos))
' "$1" "$2"
}

# Arquivos do <lista> (NUL) numa linha só, separados por vírgula.
juntar() {  # <lista>
  tr '\0' '\n' <"$1" | paste -sd ',' - | sed 's/,/, /g'
}

# Motivo de um código do gitleaks que não é 0 nem GITLEAKS_ACHOU.
motivo_falha() {  # <código> <log>
  case "$1" in
    124|137) echo "gitleaks passou de $GITLEAKS_TIMEOUT s e foi parado" ;;
    *) echo "gitleaks não rodou (docker run saiu com $1; veja $2)" ;;
  esac
}

# gitleaks no stage. 0 = limpo (o que sobrou no stage pode ser comitado); 1 = falhou (já tirou tudo do stage).
# Achou: tira do stage só os arquivos do relatório, loga ERRO e confere o resto de novo (até 2 vezes). O relatório da
# primeira varredura é gitleaks.json; o da conferência, gitleaks-2.json.
varrer_stage() {
  local falta relatorio saida lista="$LOG_DIR/gitleaks-arquivos" codigo tentativa arquivos
  if falta="$(falta_para_o_gitleaks)"; then nao_comitar "$falta"; return 1; fi
  rm -f "$LOG_DIR/gitleaks-2.json" "$LOG_DIR/gitleaks-2.log"
  for tentativa in 1 2 3; do
    [ -n "$("${GIT[@]}" diff --cached --name-only)" ] || return 0  # nada mais no stage
    if [ "$tentativa" -eq 3 ]; then nao_comitar "gitleaks ainda acha segredo depois de tirar os arquivos do stage"; return 1; fi
    relatorio="$LOG_DIR/gitleaks.json" saida="$LOG_DIR/gitleaks.log"
    [ "$tentativa" -eq 1 ] || relatorio="$LOG_DIR/gitleaks-$tentativa.json" saida="$LOG_DIR/gitleaks-$tentativa.log"
    rodar_gitleaks stage "$relatorio" "$saida" --staged
    codigo=$?
    [ -f "$relatorio" ] && chmod 600 "$relatorio"
    if [ "$codigo" -eq 0 ]; then
      [ -f "$relatorio" ] && resumir_relatorio "$relatorio" "$lista" >/dev/null 2>&1
      log "gitleaks: nada com cara de segredo no stage."
      return 0
    fi
    if [ "$codigo" -ne "$GITLEAKS_ACHOU" ]; then nao_comitar "$(motivo_falha "$codigo" "$saida")"; return 1; fi
    if ! resumir_relatorio "$relatorio" "$lista" 2>>"$saida" || [ ! -s "$lista" ]; then
      nao_comitar "gitleaks achou segredo e não consegui ler os arquivos do relatório ($relatorio)"; return 1
    fi
    arquivos=()
    while IFS= read -r -d '' f; do arquivos+=("$f"); done <"$lista"
    if ! "${GIT[@]}" --literal-pathspecs reset -q -- "${arquivos[@]}"; then
      nao_comitar "gitleaks achou segredo e o git reset dos arquivos falhou"; return 1
    fi
    erro "gitleaks achou segredo em: $(juntar "$lista"); esses arquivos ficaram fora do commit de hoje (o disco não muda). Tire o segredo (o valor vai para o cofre; na nota fica {{segredo:NOME}})."
  done
}

# gitleaks nos commits desde a última varredura limpa. 0 = limpo (pode fazer push); 1 = achou ou falhou (sem push).
varrer_commits() {
  local falta relatorio="$LOG_DIR/gitleaks-commits.json" saida="$LOG_DIR/gitleaks-commits.log"
  local lista="$LOG_DIR/gitleaks-commits-arquivos" topo ultimo codigo
  topo="$("${GIT[@]}" rev-parse --verify -q 'HEAD^{commit}')" || { log "repositório sem commit; nada a varrer."; return 0; }
  ultimo="$(tr -d '[:space:]' 2>/dev/null <"$ULTIMO_VARRIDO")"
  if [ "$ultimo" = "$topo" ]; then
    log "gitleaks: nenhum commit novo desde a última varredura."
    TOPO_VARRIDO="$topo"
    return 0
  fi
  local opcoes=()
  if [[ "$ultimo" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] && "${GIT[@]}" merge-base --is-ancestor "$ultimo" "$topo" 2>/dev/null; then
    opcoes=(--log-opts "$ultimo..$topo")
  else
    # Primeira vez (ou o histórico foi reescrito): o histórico inteiro, uma vez.
    log "gitleaks: sem varredura anterior que valha; varro o histórico inteiro."
  fi
  if falta="$(falta_para_o_gitleaks)"; then erro "$falta; sem push."; return 1; fi
  rodar_gitleaks commits "$relatorio" "$saida" ${opcoes[@]+"${opcoes[@]}"}
  codigo=$?
  [ -f "$relatorio" ] && chmod 600 "$relatorio"
  if [ "$codigo" -eq 0 ]; then
    [ -f "$relatorio" ] && resumir_relatorio "$relatorio" "$lista" >/dev/null 2>&1
    echo "$topo" >"$ULTIMO_VARRIDO" && chmod 600 "$ULTIMO_VARRIDO"
    TOPO_VARRIDO="$topo"
    log "gitleaks: nada com cara de segredo nos commits até ${topo:0:12}."
    return 0
  fi
  if [ "$codigo" -ne "$GITLEAKS_ACHOU" ]; then erro "$(motivo_falha "$codigo" "$saida") nos commits; sem push."; return 1; fi
  if resumir_relatorio "$relatorio" "$lista" 2>>"$saida" && [ -s "$lista" ]; then
    erro "gitleaks achou segredo em commits já feitos, nos arquivos: $(juntar "$lista"); sem push. Nada foi apagado: tire o segredo do histórico (git filter-repo) ou, se aceita o risco, grave o id do HEAD em $ULTIMO_VARRIDO. Detalhe (sem o valor) em $relatorio."
  else
    erro "gitleaks achou segredo em commits já feitos (veja $relatorio); sem push."
  fi
  return 1
}

# git add de tudo, menos o que o Syncthing deixa na pasta (versões, marcador, temporários) e um .git guardado por
# engano. O servidor pode comitar uma escrita da IA entre a espera do index.lock e o add: com o lock ocupado, tenta de
# novo (3 vezes, ESPERA_ADD s entre elas).
adicionar() {
  local tentativa saida
  for tentativa in 1 2 3; do
    if saida="$("${GIT[@]}" -c core.excludesFile="$IGNORAR_SEMPRE" add -A -- . 2>&1)"; then
      [ -z "$saida" ] || printf '%s\n' "$saida"
      return 0
    fi
    case "$saida" in
      *index.lock*)
        if [ "$tentativa" -lt 3 ]; then
          log "index.lock ocupado no git add (o servidor comitando); tento de novo em $ESPERA_ADD s."
          sleep "$ESPERA_ADD"
        fi ;;
      *) break ;;
    esac
  done
  printf '%s\n' "$saida"
  return 1
}

# Push do commit varrido para a branch atual. ssh só com a chave de deploy (o core.sshCommand do repositório não
# vale), BatchMode (nunca pergunta), só o protocolo ssh (remoto que é pasta local rodaria o receivepack da config
# aqui) e sem credential.helper do repositório.
enviar() {
  local branch
  if [ -z "$TOPO_VARRIDO" ]; then log "nada varrido para enviar; sem push."; return 0; fi
  if [ ! -f "$CHAVE_SSH" ]; then
    erro "não achei a chave de deploy em $CHAVE_SSH (VAULT_SSH_CHAVE); sem push. O commit local ficou."; return 1
  fi
  case "$CHAVE_SSH" in *"'"*) erro "o caminho da chave de deploy tem aspas simples; sem push."; return 1 ;; esac
  if ! branch="$("${GIT[@]}" symbolic-ref --short -q HEAD)"; then
    erro "HEAD solto (fora de uma branch); sem push. O commit local ficou."; return 1
  fi
  if git "${SEGURO[@]}" -c core.sshCommand="ssh -i '$CHAVE_SSH' -o IdentitiesOnly=yes -o BatchMode=yes" \
    -c protocol.allow=never -c protocol.ssh.allow=always -c credential.helper= \
    push origin "$TOPO_VARRIDO:refs/heads/$branch"; then
    log "push feito (${TOPO_VARRIDO:0:12} para $branch)."
  else
    erro "git push falhou (credencial ou rede). O commit local ficou."
  fi
}

# Hora da última execução sem ERRO (com ou sem mudança), para o lint diário. Modo 644: o lint pode rodar com outro
# usuário. Falhar aqui não é ERRO (o commit e o push já valeram).
gravar_carimbo() {
  if mkdir -p "$LOG_DIR" 2>/dev/null && date +%s 2>/dev/null >"$CARIMBO.parcial" && chmod 644 "$CARIMBO.parcial" && mv -f "$CARIMBO.parcial" "$CARIMBO"; then
    return 0
  fi
  rm -f "$CARIMBO.parcial"
  log "AVISO: não gravei $CARIMBO; o lint diário pode avisar de commit parado."
}

if motivo="$(recusa_do_vault)"; then
  erro "$motivo; nada foi comitado hoje."
  exit 1
fi

if [ -z "$("${GIT[@]}" status --porcelain)" ]; then
  log "sem mudanças em $(date +%F); nada a comitar."
else
  adicionar || { log "ERRO: git add falhou."; exit 1; }
  varrer_stage || exit 1
  N="$("${GIT[@]}" diff --cached --name-only | wc -l | tr -d ' ')"
  if [ "$N" -eq 0 ]; then
    log "nada sobrou para comitar em $(date +%F)."
  else
    "${GIT[@]}" commit -q --no-verify -m "vault: $(date +%F) (${N} arquivos)" || { log "ERRO: git commit falhou."; exit 1; }
    log "commit feito em $(date +%F): ${N} arquivos."
  fi
fi

# Commits por escrita do servidor, fotos e o de hoje: varridos antes de qualquer push.
if ! varrer_commits; then
  exit 1
fi

if [ "$VAULT_PUSH" = "1" ]; then
  enviar
else
  log "push desligado (VAULT_PUSH não é 1)."
fi
[ "$ERROS" -ne 0 ] || gravar_carimbo
exit "$ERROS"
