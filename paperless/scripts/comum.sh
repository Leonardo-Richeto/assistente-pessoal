#!/usr/bin/env bash
# Funções comuns dos scripts do Paperless único (Ficha 6). Não roda sozinho:
# `source "$(dirname "$0")/comum.sh"`. Reaproveita scripts/lib.sh do assistente (log, age, hashes,
# esperar_saudavel, retenção) e troca o `dc` pelo compose de paperless/.
#
# Onde fica o estado: PAPERLESS_HOME (variável de ambiente, obrigatória). Nunca adivinha.

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"

PAPERLESS_APP="$APP/paperless"
GESTAO="$PAPERLESS_APP/deploy/gestao.py"
PREFIXO_PACOTE=paperless
PADRAO_PACOTE='paperless-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*.tar.age'

descobrir_home() {
  [ -n "${PAPERLESS_HOME:-}" ] || falha "defina PAPERLESS_HOME=<pasta do estado do Paperless> (ex.: /srv/paperless)."
  HOME_DIR="$(absoluto "$PAPERLESS_HOME")"
  HOME_DIR="${HOME_DIR%/}"
  ENV_FILE="$HOME_DIR/.env"
}

OBRIGATORIAS=(PAPERLESS_HOME COMPOSE_PROJECT_NAME PAPERLESS_DBPASS PAPERLESS_SECRET_KEY PAPERLESS_ADMIN_USER USUARIOS)

conferir_env() {
  [ -f "$ENV_FILE" ] || falha "sem $ENV_FILE. Copie paperless/.env.example para lá e preencha."
  local faltam=() vazias=() chave
  while IFS= read -r chave; do
    tem_chave_env "$chave" || faltam+=("$chave")
  done < <(grep -E '^[A-Z][A-Z0-9_]*=' "$PAPERLESS_APP/.env.example" | cut -d= -f1)
  [ "${#faltam[@]}" -eq 0 ] || falha "variáveis de paperless/.env.example ausentes em $ENV_FILE: ${faltam[*]}"
  for chave in "${OBRIGATORIAS[@]}"; do
    [ -n "$(valor_env "$chave")" ] || vazias+=("$chave")
  done
  [ "${#vazias[@]}" -eq 0 ] || falha "variáveis obrigatórias vazias em $ENV_FILE: ${vazias[*]}"
  local home_env
  home_env="$(absoluto "$(valor_env PAPERLESS_HOME)")"
  [ "${home_env%/}" = "$HOME_DIR" ] \
    || falha "PAPERLESS_HOME do .env ($home_env) não é a pasta do .env ($HOME_DIR)."
  local u
  for u in $(valor_env USUARIOS); do
    [[ "$u" =~ ^[a-z][a-z0-9_]{0,29}$ ]] || falha "nome inválido em USUARIOS: '$u' (minúsculas, dígitos e _)."
    [ "$u" != "$(valor_env PAPERLESS_ADMIN_USER)" ] || falha "o admin não pode estar em USUARIOS."
  done
}

dc() {
  docker compose --project-directory "$(caminho_docker "$PAPERLESS_APP")" \
    -f "$(caminho_docker "$PAPERLESS_APP/docker-compose.yml")" --env-file "$(caminho_docker "$ENV_FILE")" "$@"
}

# gestao <ação> [VAR=valor ...] -> saída do paperless/deploy/gestao.py no webserver.
gestao() {
  local acao="$1"; shift
  local extras=() kv
  for kv in "$@"; do extras+=(-e "$kv"); done
  dc exec -T -u paperless -e GESTAO_ACAO="$acao" -e USUARIOS="$(valor_env USUARIOS)" \
    -e ADMIN="$(valor_env PAPERLESS_ADMIN_USER)" ${extras[@]+"${extras[@]}"} webserver python3 manage.py shell -v 0 <"$GESTAO" \
    | tr -d '\r' | sed '/^$/d'
}

# Pastas do estado, com dono uid 1000 (USERMAP_UID do webserver) onde o Paperless grava.
criar_pastas() {
  local u
  mkdir -p "$HOME_DIR"/{data/postgres,data/redis,data/paperless,data/media,export,backups,consumir} \
    || falha "não consegui criar as pastas em $HOME_DIR."
  for u in $(valor_env USUARIOS); do mkdir -p "$HOME_DIR/consumir/$u"; done
  chmod 700 "$HOME_DIR" 2>/dev/null || true
}

# Rede que o assistente usa, vista do host: 127.0.0.1 e nada mais.
conferir_porta() {
  local id saida
  id="$(dc ps -q webserver 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$id" ] || { echo "porta: webserver parado"; return 1; }
  saida="$(docker port "$id" 8000/tcp 2>/dev/null | tr -d '\r')"
  if [ -n "$saida" ] && ! printf '%s\n' "$saida" | grep -vq '^127\.0\.0\.1:'; then
    echo "porta: $saida (só loopback)"
  else
    echo "porta: '${saida:-nenhuma}' (esperado só 127.0.0.1)"
    return 1
  fi
}
