#!/usr/bin/env bash
# Funções comuns dos scripts de fotos (Ficha 17). Não roda sozinho: `source "$(dirname "$0")/comum.sh"`.
# Reaproveita scripts/lib.sh do assistente (log, esperar_saudavel, valor_env) e troca o `dc` pelo compose de fotos/.
#
# Onde fica o estado: FOTOS_HOME (variável de ambiente, obrigatória). Nunca adivinha.

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"

FOTOS_APP="$APP/fotos"

descobrir_home() {
  [ -n "${FOTOS_HOME:-}" ] || falha "defina FOTOS_HOME=<pasta do estado das fotos> (ex.: /srv/fotos)."
  HOME_DIR="$(absoluto "$FOTOS_HOME")"
  HOME_DIR="${HOME_DIR%/}"
  ENV_FILE="$HOME_DIR/.env"
}

OBRIGATORIAS=(FOTOS_HOME COMPOSE_PROJECT_NAME DB_PASSWORD)

conferir_env() {
  [ -f "$ENV_FILE" ] || falha "sem $ENV_FILE. Copie fotos/.env.example para lá e preencha."
  local faltam=() vazias=() chave
  while IFS= read -r chave; do
    tem_chave_env "$chave" || faltam+=("$chave")
  done < <(grep -E '^[A-Z][A-Z0-9_]*=' "$FOTOS_APP/.env.example" | cut -d= -f1)
  [ "${#faltam[@]}" -eq 0 ] || falha "variáveis de fotos/.env.example ausentes em $ENV_FILE: ${faltam[*]}"
  for chave in "${OBRIGATORIAS[@]}"; do
    [ -n "$(valor_env "$chave")" ] || vazias+=("$chave")
  done
  [ "${#vazias[@]}" -eq 0 ] || falha "variáveis obrigatórias vazias em $ENV_FILE: ${vazias[*]}"
  local home_env
  home_env="$(absoluto "$(valor_env FOTOS_HOME)")"
  [ "${home_env%/}" = "$HOME_DIR" ] || falha "FOTOS_HOME do .env ($home_env) não é a pasta do .env ($HOME_DIR)."
  [[ "$(valor_env DB_PASSWORD)" =~ ^[A-Za-z0-9]+$ ]] || falha "DB_PASSWORD só com letras e números (exigência do Immich)."
  local lan; lan="$(valor_env ENDERECO_LAN)"
  [ -z "$lan" ] || [[ "$lan" =~ ^(10|172|192)\.[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || falha "ENDERECO_LAN ($lan) não é um IP da rede local (10.x, 172.x ou 192.x)."
  # Ficha 17, regra 6: o ML só sobe na janela semanal, nunca pelo COMPOSE_PROFILES.
  case ",$(valor_env COMPOSE_PROFILES)," in
    *,ml,*) falha "perfil ml no COMPOSE_PROFILES: o ML ficaria ligado o tempo todo (Ficha 17, regra 6)." ;;
  esac
}

# Com ENDERECO_LAN no .env, junta a porta da rede de casa, salvo FOTOS_SO_LOOPBACK=1 (antes do administrador).
dc() {
  local arquivos=(-f "$(caminho_docker "$FOTOS_APP/docker-compose.yml")")
  if [ -n "$(valor_env ENDERECO_LAN)" ] && [ "${FOTOS_SO_LOOPBACK:-0}" != 1 ]; then
    arquivos+=(-f "$(caminho_docker "$FOTOS_APP/docker-compose.lan.yml")")
  fi
  docker compose --project-directory "$(caminho_docker "$FOTOS_APP")" "${arquivos[@]}" \
    --env-file "$(caminho_docker "$ENV_FILE")" "$@"
}

com_lan() { [ -n "$(valor_env ENDERECO_LAN)" ]; }

porta_host() { local p; p="$(valor_env PORTA_HOST)"; echo "${p:-8040}"; }
base_local() { echo "http://127.0.0.1:$(porta_host)"; }

criar_pastas() {
  local d
  for d in biblioteca postgres modelos; do
    mkdir -p "$HOME_DIR/data/$d" || falha "não consegui criar $HOME_DIR/data/$d."
  done
  chmod 700 "$HOME_DIR" 2>/dev/null || true
}

# O primeiro a abrir a página vira administrador. Enquanto não houver administrador, o Immich fica só no loopback.
# Resposta: "sim", "nao" ou vazio (sem resposta).
inicializado() {
  curl -s -m 5 "$(base_local)/api/server/config" | python3 -c '
import json, sys
try:
    print("sim" if json.load(sys.stdin).get("isInitialized") else "nao")
except Exception:
    pass'
}

# Saudável no loopback: <http://127.0.0.1:porta>
responde() { curl -s -m 5 "$1/api/server/ping" | grep -q pong; }

conferir_porta() {
  local id saida
  id="$(dc ps -q immich-server 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$id" ] || { echo "porta: immich-server parado"; return 1; }
  # Só o loopback e, com ENDERECO_LAN, o IP da rede de casa. 0.0.0.0 (todas as interfaces, inclusive a do
  # Tailscale) é problema.
  local permitido='^127\.0\.0\.1:'
  com_lan && permitido="^(127\\.0\\.0\\.1|$(valor_env ENDERECO_LAN | sed 's/\./\\./g')):"
  saida="$(docker port "$id" 2283/tcp 2>/dev/null | tr -d '\r' | tr '\n' ' ')"
  if [ -n "$saida" ] && ! printf '%s\n' $saida | grep -Evq "$permitido"; then
    echo "porta: $saida(loopback e rede de casa)"
  else
    echo "porta: '${saida:-nenhuma}' (esperado só 127.0.0.1 e ENDERECO_LAN)"
    return 1
  fi
}

ml_rodando() { [ -n "$(dc --profile ml ps -q --status running --status restarting immich-machine-learning 2>/dev/null | tr -d '\r')" ]; }
