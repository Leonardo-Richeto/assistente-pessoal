#!/usr/bin/env bash
# Funções comuns dos scripts da câmera (Ficha 18). Não roda sozinho: `source "$(dirname "$0")/comum.sh"`.
# Reaproveita scripts/lib.sh do assistente (log, esperar_saudavel, valor_env) e troca o `dc` pelo compose de cameras/.
#
# Onde fica o estado: CAMERAS_HOME (variável de ambiente, obrigatória). Nunca adivinha.

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"

CAMERAS_APP="$APP/cameras"

descobrir_home() {
  [ -n "${CAMERAS_HOME:-}" ] || falha "defina CAMERAS_HOME=<pasta do estado da câmera> (ex.: /srv/cameras)."
  HOME_DIR="$(absoluto "$CAMERAS_HOME")"
  HOME_DIR="${HOME_DIR%/}"
  ENV_FILE="$HOME_DIR/.env"
}

OBRIGATORIAS=(CAMERAS_HOME COMPOSE_PROJECT_NAME CAMERA_IP CAMERA_SENHA LIMITE_GRAVACOES_GB)

conferir_env() {
  [ -f "$ENV_FILE" ] || falha "sem $ENV_FILE. Copie cameras/.env.example para lá e preencha."
  local faltam=() vazias=() chave
  while IFS= read -r chave; do
    tem_chave_env "$chave" || faltam+=("$chave")
  done < <(grep -E '^[A-Z][A-Z0-9_]*=' "$CAMERAS_APP/.env.example" | cut -d= -f1)
  [ "${#faltam[@]}" -eq 0 ] || falha "variáveis de cameras/.env.example ausentes em $ENV_FILE: ${faltam[*]}"
  for chave in "${OBRIGATORIAS[@]}"; do
    [ -n "$(valor_env "$chave")" ] || vazias+=("$chave")
  done
  [ "${#vazias[@]}" -eq 0 ] || falha "variáveis obrigatórias vazias em $ENV_FILE: ${vazias[*]}"
  local home_env
  home_env="$(absoluto "$(valor_env CAMERAS_HOME)")"
  [ "${home_env%/}" = "$HOME_DIR" ] || falha "CAMERAS_HOME do .env ($home_env) não é a pasta do .env ($HOME_DIR)."
  local ip; ip="$(valor_env CAMERA_IP)"
  [[ "$ip" =~ ^(10|172|192)\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || falha "CAMERA_IP ($ip) não é um IP da rede local."
  local lan; lan="$(valor_env ENDERECO_LAN)"
  [ -z "$lan" ] || [[ "$lan" =~ ^(10|172|192)\.[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || falha "ENDERECO_LAN ($lan) não é um IP da rede local (10.x, 172.x ou 192.x)."
  # A senha entra numa URL e no .format() do Frigate: caractere especial cru quebra a URL ou o config.
  # O $ o Compose troca por variável; ? & quebram a URL; % só no formato %XX.
  local senha; senha="$(valor_env CAMERA_SENHA)"
  if [[ "$senha" =~ [#@:/{}\ \$\?\&\'\"] ]] || [[ "$senha" =~ %($|[^0-9A-Fa-f]|.$|.[^0-9A-Fa-f]) ]]; then
    falha "CAMERA_SENHA com caractere cru (# @ : / { } \$ ? & aspas ou espaço) ou % solto: use o formato de URL (# vira %23, @ vira %40, \$ vira %24)."
  fi
  local gpu; gpu="$(valor_env GPU_DRI)"
  [ -z "$gpu" ] || [ -c "$gpu" ] || falha "GPU_DRI ($gpu) não existe ou não é dispositivo (no i7: /dev/dri/renderD128)."
  [[ "$(valor_env LIMITE_GRAVACOES_GB)" =~ ^[0-9]+$ ]] || falha "LIMITE_GRAVACOES_GB precisa ser um número inteiro."
}

dc() {
  local arquivos=(-f "$(caminho_docker "$CAMERAS_APP/docker-compose.yml")")
  [ -z "$(valor_env ENDERECO_LAN)" ] || arquivos+=(-f "$(caminho_docker "$CAMERAS_APP/docker-compose.lan.yml")")
  [ -z "$(valor_env GPU_DRI)" ] || arquivos+=(-f "$(caminho_docker "$CAMERAS_APP/docker-compose.gpu.yml")")
  docker compose --project-directory "$(caminho_docker "$CAMERAS_APP")" "${arquivos[@]}" \
    --env-file "$(caminho_docker "$ENV_FILE")" "$@"
}

com_lan() { [ -n "$(valor_env ENDERECO_LAN)" ]; }

criar_pastas() {
  local d
  for d in config gravacoes; do
    mkdir -p "$HOME_DIR/$d" || falha "não consegui criar $HOME_DIR/$d."
  done
  chmod 700 "$HOME_DIR" 2>/dev/null || true
}

# API interna do Frigate (porta 5000, sem login), só de dentro do container.
api() { dc exec -T frigate curl -fsS -m 10 "http://127.0.0.1:5000/api/$1" 2>/dev/null; }

# Gravação mais nova em minutos (vazio = nenhuma).
minutos_ultima_gravacao() {
  # Sem xargs: com zero arquivos, o xargs do Linux roda `ls` na pasta atual e daria uma idade falsa.
  local t
  t="$(find "$HOME_DIR/gravacoes/recordings" -name '*.mp4' -mmin -1440 -exec stat -c %Y {} + 2>/dev/null \
       || find "$HOME_DIR/gravacoes/recordings" -name '*.mp4' -mmin -1440 -exec stat -f %m {} + 2>/dev/null)"
  t="$(printf '%s\n' "$t" | grep -E '^[0-9]+$' | sort -n | tail -n 1)"
  [ -n "$t" ] || return 0
  echo $(( ( $(date +%s) - t ) / 60 ))
}

conferir_porta() {
  local id saida p ruim=0
  id="$(dc ps -q frigate 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$id" ] || { echo "porta: frigate parado"; return 1; }
  # Ficha 18, regra 5: nenhuma porta além da 8971; a 8971 só no loopback e, com ENDERECO_LAN, no IP de casa.
  for p in 5000 8554 8555; do
    [ -z "$(docker port "$id" "$p/tcp" 2>/dev/null)" ] || { echo "porta: $p publicada (só a 8971 pode)"; ruim=1; }
  done
  local permitido='^127\.0\.0\.1:'
  com_lan && permitido="^(127\\.0\\.0\\.1|$(valor_env ENDERECO_LAN | sed 's/\./\\./g')):"
  saida="$(docker port "$id" 8971/tcp 2>/dev/null | tr -d '\r' | tr '\n' ' ')"
  if [ -n "$saida" ] && ! printf '%s\n' $saida | grep -Evq "$permitido"; then
    [ "$ruim" -eq 0 ] && echo "porta: $saida(loopback e rede de casa)"
  else
    echo "porta: '${saida:-nenhuma}' (esperado só 127.0.0.1 e ENDERECO_LAN)"
    ruim=1
  fi
  return "$ruim"
}
