#!/usr/bin/env bash
# Atualiza todas as instâncias do i7 com o código do GitHub, uma de cada vez (a do Leonardo primeiro).
#   bash scripts/atualizar.sh                     # todas: /srv/assistente e depois /srv/assistente-*
#   bash scripts/atualizar.sh --so assistente     # só uma (nome da pasta em /srv)
#
# Cada instância tem o próprio clone em <home>/app. Para cada uma, nesta ordem:
#   1. git pull --ff-only; se o commit for o último que passou nesta instância (<home>/.atualizado), pula;
#   2. sudo preparar_host.sh, se mudou timer (deploy/systemd, deploy/vault) ou o próprio preparar_host.sh desde o
#      último commit que passou (sem esse registro, roda sempre);
#   3. docker compose up -d --build (a migração do banco roda sozinha);
#   4. scripts/verificar.sh; passou, o commit vai para <home>/.atualizado.
# Se uma falhar, para e não mexe nas seguintes: a do Leonardo serve de teste para a da Nathalia.
# Não mexe no Paperless nem no cofre (projetos próprios, em paperless/ e cofre/): só avisa se mudaram.
source "$(dirname "$0")/lib.sh"

BASE="${ATUALIZAR_BASE:-/srv}"
SO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --so) SO="${2:-}"; shift 2 || falha "--so precisa do nome da pasta (ex.: assistente)." ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) falha "opção desconhecida: $1 (veja --help)" ;;
  esac
done

INSTANCIAS=()
for home in "$BASE/assistente" "$BASE"/assistente-*; do
  [ -d "$home/app/.git" ] && [ -f "$home/.env" ] || continue
  [ -z "$SO" ] || [ "$(basename "$home")" = "$SO" ] || continue
  INSTANCIAS+=("$home")
done
[ "${#INSTANCIAS[@]}" -gt 0 ] || falha "nenhuma instância em $BASE${SO:+ com o nome $SO} (precisa de app/.git e .env)."
log "instâncias, nesta ordem: ${INSTANCIAS[*]}"

for home in "${INSTANCIAS[@]}"; do
  app="$home/app"
  nome="$(basename "$home")"
  log "--- $nome"
  # Último commit que passou no verificar.sh; o HEAD do clone não serve (o pull pode ter ido e o build falhado).
  antes="$(cat "$home/.atualizado" 2>/dev/null || true)"
  git -C "$app" pull --ff-only -q || falha "$nome: git pull falhou (mudança local no clone?). Nada mais foi feito."
  depois="$(git -C "$app" rev-parse HEAD)" || falha "$nome: não consegui ler o commit atual."
  if [ "$antes" = "$depois" ]; then
    log "$nome: já está no commit ${depois:0:7}; nada a fazer."
    continue
  fi
  if [ -n "$antes" ] && mudou="$(git -C "$app" diff --name-only "$antes" "$depois" 2>/dev/null)"; then
    log "$nome: ${antes:0:7} -> ${depois:0:7}"
    timers=0
    printf '%s\n' "$mudou" | grep -Eq '^(deploy/systemd/|deploy/vault/|scripts/preparar_host\.sh$)' && timers=1
  else
    log "$nome: sem registro do último commit bom; sobe tudo no ${depois:0:7}"
    mudou=""; timers=1
  fi

  if [ "$timers" -eq 1 ]; then
    log "$nome: timers mudaram; rodando o preparar_host.sh (pede a senha do sudo)"
    sudo ASSISTENTE_HOME="$home" bash "$app/scripts/preparar_host.sh" >/dev/null \
      || falha "$nome: preparar_host.sh falhou. Rode à mão: sudo ASSISTENTE_HOME=$home bash $app/scripts/preparar_host.sh"
  fi

  log "$nome: docker compose up -d --build"
  (cd "$app" && docker compose up -d --build --quiet-pull >/dev/null) \
    || falha "$nome: docker compose up falhou. Veja: cd $app && docker compose ps"

  log "$nome: verificar.sh"
  ASSISTENTE_HOME="$home" bash "$app/scripts/verificar.sh" \
    || falha "$nome: verificar.sh falhou; as seguintes não foram atualizadas. Se for só o Funnel, espere ~20 min e rode de novo (esta é pulada)."

  if printf '%s\n' "$mudou" | grep -Eq '^(paperless|cofre)/'; then
    aviso "$nome: paperless/ ou cofre/ mudaram. Eles não sobem por aqui: siga docs/IMPLANTACAO.md."
  fi
  printf '%s\n' "$depois" >"$home/.atualizado"
  log "$nome: ok"
done
log "feito."
