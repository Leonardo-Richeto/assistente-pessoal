#!/usr/bin/env bash
# Conferência diária do cofre (Ficha 11; timer cofre-conferir). Sai com erro se achar: Vaultwarden fora do ar;
# cadastro aberto (pelo ambiente ou de fato, pela API); config.json (passa por cima do ambiente); painel /admin
# ligado; porta fora do 127.0.0.1; Funnel no serve.json; Tailscale doente com o perfil ligado; ADMIN_TOKEN ou
# SIGNUPS_ALLOWED no .env.
#
#   COFRE_HOME=/srv/cofre cofre/scripts/conferir.sh
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,5p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac
descobrir_home
conferir_env

erros=0
problema() { echo "$NOME_SCRIPT: PROBLEMA: $*"; erros=1; }
porta="$(valor_env PORTA_HOST)"; porta="${porta:-8030}"
base="http://127.0.0.1:$porta"

[ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$base/alive")" = 200 ] || problema "o Vaultwarden não responde em $base/alive."
[ "$(env_no_container SIGNUPS_ALLOWED)" = false ] || problema "cadastro aberto (rode cofre/scripts/cadastro.sh fechar)."
cadastro_aberto "$base" && problema "o cadastro aceita conta nova (rode cofre/scripts/cadastro.sh fechar)."
[ ! -e "$DADOS/config.json" ] || problema "$DADOS/config.json existe: ele passa por cima do .env (apague-o com o cofre parado)."
[ -z "$(env_no_container ADMIN_TOKEN)" ] || problema "ADMIN_TOKEN no container: o painel está ligado."
painel_desligado "$base" || problema "o painel /admin está ligado (esperado: \"admin panel is disabled\")."
grep -q AllowFunnel "$COFRE_APP/deploy/serve.json" && problema "AllowFunnel no serve.json: o cofre não vai para a internet."
if perfil_tailscale; then
  esperar_saudavel tailscale 90 >/dev/null 2>&1 \
    || problema "o Tailscale não está saudável (o Serve pode estar dando 502): cofre/scripts/preparar.sh recria os dois."
fi
linha="$(conferir_porta)" || erros=1
log "$linha"
[ "$erros" -eq 0 ] || { aviso "Ficha 11 violada (veja acima)."; exit 1; }
log "ok"
