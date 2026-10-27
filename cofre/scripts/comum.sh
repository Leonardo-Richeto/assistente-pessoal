#!/usr/bin/env bash
# Funções comuns dos scripts do cofre (Ficha 11). Não roda sozinho: `source "$(dirname "$0")/comum.sh"`.
# Reaproveita scripts/lib.sh do assistente (log, age, hashes, esperar_saudavel, retenção) e troca o `dc`
# pelo compose de cofre/.
#
# Onde fica o estado: COFRE_HOME (variável de ambiente, obrigatória). Nunca adivinha.

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"

COFRE_APP="$APP/cofre"
PREFIXO_PACOTE=cofre
PADRAO_PACOTE='cofre-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*.tar.age'

descobrir_home() {
  [ -n "${COFRE_HOME:-}" ] || falha "defina COFRE_HOME=<pasta do estado do cofre> (ex.: /srv/cofre)."
  HOME_DIR="$(absoluto "$COFRE_HOME")"
  HOME_DIR="${HOME_DIR%/}"
  ENV_FILE="$HOME_DIR/.env"
  DADOS="$HOME_DIR/data/vaultwarden"
}

OBRIGATORIAS=(COFRE_HOME COMPOSE_PROJECT_NAME DOMINIO)

conferir_env() {
  [ -f "$ENV_FILE" ] || falha "sem $ENV_FILE. Copie cofre/.env.example para lá e preencha."
  local faltam=() vazias=() chave
  while IFS= read -r chave; do
    tem_chave_env "$chave" || faltam+=("$chave")
  done < <(grep -E '^[A-Z][A-Z0-9_]*=' "$COFRE_APP/.env.example" | cut -d= -f1)
  [ "${#faltam[@]}" -eq 0 ] || falha "variáveis de cofre/.env.example ausentes em $ENV_FILE: ${faltam[*]}"
  for chave in "${OBRIGATORIAS[@]}"; do
    [ -n "$(valor_env "$chave")" ] || vazias+=("$chave")
  done
  [ "${#vazias[@]}" -eq 0 ] || falha "variáveis obrigatórias vazias em $ENV_FILE: ${vazias[*]}"
  local home_env
  home_env="$(absoluto "$(valor_env COFRE_HOME)")"
  [ "${home_env%/}" = "$HOME_DIR" ] || falha "COFRE_HOME do .env ($home_env) não é a pasta do .env ($HOME_DIR)."
  case ",$(valor_env COMPOSE_PROFILES)," in
    *,tailscale,*) [ -n "$(valor_env TS_NOME)" ] || falha "perfil tailscale ligado sem TS_NOME." ;;
  esac
  # Ficha 11, regras 3 e 4: o painel só existe com ADMIN_TOKEN, e o cadastro só abre pelo cadastro.sh. Nenhum dos
  # dois mora no .env (um docker compose up direto abriria o cadastro ou ligaria o painel).
  ! tem_chave_env ADMIN_TOKEN || falha "ADMIN_TOKEN no $ENV_FILE: o painel fica desligado (Ficha 11, regra 4)."
  ! tem_chave_env SIGNUPS_ALLOWED || falha "SIGNUPS_ALLOWED no $ENV_FILE: o cadastro só abre pelo cadastro.sh (Ficha 11, regra 3)."
}

dc() {
  docker compose --project-directory "$(caminho_docker "$COFRE_APP")" \
    -f "$(caminho_docker "$COFRE_APP/docker-compose.yml")" --env-file "$(caminho_docker "$ENV_FILE")" "$@"
}

perfil_tailscale() { case ",$(valor_env COMPOSE_PROFILES)," in *,tailscale,*) return 0 ;; esac; return 1; }

criar_pastas() {
  mkdir -p "$DADOS" "$HOME_DIR/data/tailscale" "$HOME_DIR/backups" || falha "não consegui criar as pastas em $HOME_DIR."
  chmod 700 "$HOME_DIR" "$DADOS" 2>/dev/null || true
}

# (Re)sobe o Vaultwarden; com SIGNUPS_ALLOWED=true no ambiente, com o cadastro aberto. O Tailscale divide a rede
# do Vaultwarden: recriado o Vaultwarden, o Tailscale é recriado junto (senão fica sem rede).
subir() {
  local servicos=(vaultwarden)
  perfil_tailscale && servicos+=(tailscale)
  dc_quieto up -d --force-recreate "${servicos[@]}" || falha "docker compose up falhou."
  esperar_saudavel vaultwarden 180 || falha "o Vaultwarden não ficou saudável (docker compose logs vaultwarden)."
}

# Cópia consistente do banco com o cofre de pé (API de backup do SQLite, Ficha 11, regra 7): <destino.sqlite3>
copiar_banco() {
  python3 - "$DADOS/db.sqlite3" "$1" <<'PY' || falha "não consegui copiar o banco do cofre."
import sqlite3, sys
origem = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destino = sqlite3.connect(sys.argv[2])
with destino:
    origem.backup(destino)
destino.close(); origem.close()
PY
}

# Linhas por tabela de um banco SQLite do cofre, "tabela<TAB>n", em ordem: <banco.sqlite3>
contar() {
  python3 - "$1" <<'PY'
import sqlite3, sys
cx = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tabelas = [t for (t,) in cx.execute("select name from sqlite_master where type='table' "
                                     "and name not like 'sqlite_%' and name != '__diesel_schema_migrations' order by name")]
for t in tabelas:
    n = cx.execute('select count(*) from "' + t + '"').fetchone()[0]
    print(f"{t}\t{n}")
PY
}

# Variáveis em vigor no container (não no .env): <NOME>
env_no_container() {
  local id
  id="$(dc ps -q vaultwarden 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$id" ] || return 1
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$id" | tr -d '\r' | sed -n "s/^$1=//p" | head -n 1
}

# Sem ADMIN_TOKEN, o Vaultwarden 1.37 responde 200 em /admin com o aviso de painel desligado e 404 nas páginas dele.
painel_desligado() {  # <http://127.0.0.1:porta>
  curl -s -m 5 "$1/admin" | grep -q "admin panel is disabled" \
    && [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$1/admin/diagnostics")" = 404 ]
}

# O cadastro aceita conta de fato? Pede o token de verificação, como o app faria (sem e-mail configurado, o
# Vaultwarden devolve o token na resposta; nenhuma conta é criada). Vale também para o config.json, que passa por
# cima do ambiente. <http://127.0.0.1:porta>
cadastro_aberto() {
  curl -s -m 5 -H 'Content-Type: application/json' -X POST "$1/identity/accounts/register/send-verification-email" \
    -d '{"email": "conferencia@exemplo.invalid", "name": "Conferencia", "receiveMarketingEmails": false}' \
    | grep -Eq '^"?[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"?$'
}

# Texto aberto que um backup ou uma importação interrompidos (queda de energia, SIGKILL) deixaram para trás.
limpar_sobras() {
  rm -rf "$HOME_DIR"/backups/.tmp-exportar-* "$HOME_DIR"/.tmp-importar-* 2>/dev/null || true
}

conferir_porta() {
  local id saida
  id="$(dc ps -q vaultwarden 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$id" ] || { echo "porta: vaultwarden parado"; return 1; }
  saida="$(docker port "$id" 8080/tcp 2>/dev/null | tr -d '\r')"
  if [ -n "$saida" ] && ! printf '%s\n' "$saida" | grep -vq '^127\.0\.0\.1:'; then
    echo "porta: $saida (só loopback)"
  else
    echo "porta: '${saida:-nenhuma}' (esperado só 127.0.0.1)"
    return 1
  fi
}
