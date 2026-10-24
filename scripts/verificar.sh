#!/usr/bin/env bash
# Confere se o assistente está de pé e íntegro. Sai com erro se qualquer item falhar.
#
#   scripts/verificar.sh                         # serviços, consulta pelo MCP, login, Funnel
#   scripts/verificar.sh --contagens <tsv>       # + linhas por tabela iguais às do arquivo
#
# A contagem só faz sentido logo depois do importar (o importar.sh passa o arquivo); com o uso,
# as tabelas crescem. A consulta pelo MCP só lê e não grava nada, nem em `chamadas`.
source "$(dirname "$0")/lib.sh"

CONTAGENS=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --contagens) CONTAGENS="${2:-}"; shift 2 || falha "--contagens precisa do arquivo." ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) falha "opção desconhecida: $1 (veja --help)" ;;
  esac
done

descobrir_home
conferir_env

FALHAS=0
ok() { echo "ok    $*"; }
ruim() { echo "FALHA $*"; FALHAS=$((FALHAS + 1)); }

# --- Serviços (só os dos perfis ligados) -------------------------------------------------------
while IFS= read -r s; do
  [ -n "$s" ] || continue
  if [ "$s" = migracao ]; then
    id="$(dc ps -a -q migracao | tr -d '\r' | head -n 1)"
    codigo="$( [ -n "$id" ] && docker inspect -f '{{.State.ExitCode}}' "$id" 2>/dev/null | tr -d '\r')"
    [ "${codigo:-x}" = 0 ] && ok "migracao terminou com 0" || ruim "migracao: código ${codigo:-sem container}"
    continue
  fi
  if esperar_saudavel "$s" 120 2>/dev/null; then ok "$s saudável"; else ruim "$s não está saudável (docker compose ps)"; fi
done < <(dc config --services | tr -d '\r')

# --- Banco -------------------------------------------------------------------------------------
SCHEMA="$(versao_schema)"
[ -n "$SCHEMA" ] && ok "schema $SCHEMA" || ruim "sem alembic_version"
if [ -n "$CONTAGENS" ]; then
  [ -s "$CONTAGENS" ] || falha "arquivo de contagens inexistente: $CONTAGENS"
  if conferir_contagens "$CONTAGENS"; then ok "contagem de linhas igual a $CONTAGENS"; else ruim "contagem de linhas diferente"; fi
fi

# --- Consulta pelo MCP e login HTTP (dentro do container do servidor) -----------------------------
if SAIDA="$(dc exec -T servidor python -m assistente.verificacao 2>&1)"; then
  printf '%s\n' "$SAIDA" | tr -d '\r'
else
  printf '%s\n' "$SAIDA" | tr -d '\r'
  ruim "verificação dentro do servidor"
fi

# --- Paperless único (Ficha 6), só com PAPERLESS_URL: o servidor alcança, o token não é de admin, nenhum
# documento sem dono (visível às duas pessoas) e a conferência diária (paperless-conferir) não falhou. -----
if [ -n "$(valor_env PAPERLESS_URL)" ]; then
  if LINHA="$(dc exec -T servidor python - 2>&1 <<'PY'
import json, os, sys, urllib.request
url, token = os.environ["PAPERLESS_URL"].rstrip("/"), os.environ.get("PAPERLESS_API_KEY", "")
pedido = urllib.request.Request(f"{url}/api/ui_settings/", headers={"Authorization": f"Token {token}"})
try:
    usuario = json.load(urllib.request.urlopen(pedido, timeout=10))["user"]
except Exception as e:
    sys.exit(f"Paperless: {url} não respondeu com o token ({type(e).__name__})")
if usuario.get("is_superuser") or usuario.get("is_staff"):
    sys.exit(f"Paperless: o token é de superusuário ou staff ({usuario.get('username')}); use o usuário comum")
pedido = urllib.request.Request(f"{url}/api/documents/?owner__isnull=true&page_size=1",
                                headers={"Authorization": f"Token {token}"})
sem_dono = json.load(urllib.request.urlopen(pedido, timeout=10))["count"]
if sem_dono:
    sys.exit(f"Paperless: {sem_dono} documento(s) sem dono, visíveis às duas pessoas (paperless/scripts/conferir.sh)")
print(f"Paperless: {url} responde, token do usuário comum {usuario.get('username')}, nenhum documento sem dono")
PY
  )"; then ok "$(printf '%s' "$LINHA" | tr -d '\r')"; else ruim "$(printf '%s' "$LINHA" | tr -d '\r' | tail -n 1)"; fi
  if command -v systemctl >/dev/null 2>&1 && systemctl is-failed --quiet paperless-conferir.service 2>/dev/null; then
    ruim "Paperless: a conferência diária falhou (journalctl -u paperless-conferir)"
  fi
else
  echo "pulado Paperless (PAPERLESS_URL vazio)"
fi

# --- Funnel (só com o perfil tailscale) --------------------------------------------------------
if dc config --services | tr -d '\r' | grep -qx tailscale; then
  if LINHA="$(conferir_funnel_publico "$(valor_env PUBLIC_BASE_URL)")"; then ok "$LINHA"; else ruim "$LINHA"; fi
else
  echo "pulado Funnel (perfil tailscale desligado)"
fi

if [ "$FALHAS" -gt 0 ]; then
  echo "verificar: $FALHAS falha(s)."
  exit 1
fi
echo "verificar: tudo ok."
