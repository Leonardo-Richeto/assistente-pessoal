#!/usr/bin/env bash
# Funções comuns dos scripts de portabilidade (exportar, importar, verificar, preparar_host).
# Não roda sozinho: `source "$(dirname "$0")/lib.sh"`.
#
# Onde fica o estado: ASSISTENTE_HOME. Ordem de descoberta:
#   1. variável de ambiente ASSISTENTE_HOME;
#   2. a pasta acima do repositório, se o repositório se chama "app" (layout /srv/assistente/app).
# Fora disso, os scripts param e pedem a variável: nunca adivinham onde gravar.
#
# Funciona em Linux, macOS e Windows (Git Bash). Precisa de: bash, docker (com compose), tar, git.
# O age é opcional no host: sem ele, roda numa imagem própria (deploy/ferramentas).

set -uo pipefail

# No Git Bash, não deixar o MSYS reescrever argumentos que começam com "/" (caminhos de dentro
# dos containers). Caminhos do host são convertidos à mão em caminho_docker.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOME_SCRIPT="$(basename "$0" .sh)"
IMAGEM_FERRAMENTAS="assistente-ferramentas:age-1.3.2"
# Usuário do container do servidor (Dockerfile): dono de data/sessoes/oauth.
UID_SERVIDOR=1000

log() { echo "$NOME_SCRIPT: $*"; }
aviso() { echo "$NOME_SCRIPT: AVISO: $*" >&2; }
falha() { echo "$NOME_SCRIPT: ERRO: $*" >&2; exit 1; }

no_windows() { [ -n "${MSYSTEM:-}" ] || [ "${OSTYPE:-}" = "msys" ] || [ "${OSTYPE:-}" = "cygwin" ]; }

# Caminho para o bash (no Windows: /c/...).
caminho_local() {
  if no_windows && command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s\n' "$1"; fi
}

# Caminho para o docker e para o .env (no Windows: C:/...).
caminho_docker() {
  if no_windows && command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}

# Caminho absoluto, sem precisar que exista.
absoluto() {
  local p
  p="$(caminho_local "$1")"
  case "$p" in
    /*) printf '%s\n' "$p" ;;
    *) printf '%s/%s\n' "$(pwd)" "$p" ;;
  esac
}

descobrir_home() {
  if [ -n "${ASSISTENTE_HOME:-}" ]; then
    HOME_DIR="$(absoluto "$ASSISTENTE_HOME")"
  elif [ "$(basename "$APP")" = "app" ]; then
    HOME_DIR="$(cd "$APP/.." && pwd)"
  else
    falha "não sei onde fica o estado. Rode com ASSISTENTE_HOME=<pasta> (o repositório não está em <home>/app)."
  fi
  HOME_DIR="${HOME_DIR%/}"
  ENV_FILE="$HOME_DIR/.env"
}

# Valor de uma variável num arquivo .env, sem executar nada do arquivo (nada de `source`).
# Última ocorrência vale; aspas simples ou duplas em volta são tiradas.
valor_env() {
  local chave="$1" arquivo="${2:-$ENV_FILE}" linha
  linha="$(grep -E "^[[:space:]]*${chave}=" "$arquivo" 2>/dev/null | tail -n 1 | tr -d '\r')" || true
  linha="${linha#*=}"
  case "$linha" in
    \"*\") linha="${linha#\"}"; linha="${linha%\"}" ;;
    \'*\') linha="${linha#\'}"; linha="${linha%\'}" ;;
  esac
  printf '%s' "$linha"
}

tem_chave_env() { grep -Eq "^[[:space:]]*$1=" "${2:-$ENV_FILE}" 2>/dev/null; }

OBRIGATORIAS=(ASSISTENTE_HOME COMPOSE_PROJECT_NAME SENHA_DONO SENHA_LEITURA SENHA_ESCRITA JWT_SIGNING_KEY PUBLIC_BASE_URL AUTH_PROVEDOR)

# Recusa seguir se faltar variável do .env.example, se faltar valor obrigatório ou se o
# ASSISTENTE_HOME do .env não for a pasta onde o .env está.
conferir_env() {
  [ -f "$ENV_FILE" ] || falha "sem $ENV_FILE. Copie o .env.example para lá e preencha."
  local faltam=() vazias=() chave
  while IFS= read -r chave; do
    tem_chave_env "$chave" || faltam+=("$chave")
  done < <(grep -E '^[A-Z][A-Z0-9_]*=' "$APP/.env.example" | cut -d= -f1)
  [ "${#faltam[@]}" -eq 0 ] || falha "variáveis do .env.example ausentes em $ENV_FILE: ${faltam[*]}"
  for chave in "${OBRIGATORIAS[@]}"; do
    [ -n "$(valor_env "$chave")" ] || vazias+=("$chave")
  done
  [ "${#vazias[@]}" -eq 0 ] || falha "variáveis obrigatórias vazias em $ENV_FILE: ${vazias[*]}"

  local home_env
  home_env="$(absoluto "$(valor_env ASSISTENTE_HOME)")"
  [ "${home_env%/}" = "$HOME_DIR" ] \
    || falha "ASSISTENTE_HOME do .env ($home_env) não é a pasta do .env ($HOME_DIR)."
  case "$(valor_env VAULT_PATH)" in
    ""|/vault) ;;
    *) falha "VAULT_PATH agora é o caminho dentro do container: vazio ou /vault (a pasta é $HOME_DIR/vault)." ;;
  esac
  case ",$(valor_env COMPOSE_PROFILES)," in
    *,tailscale,*) [ -n "$(valor_env TS_NOME)" ] || falha "perfil tailscale ligado sem TS_NOME." ;;
  esac
}

# Arquivos do compose: COMPOSE_FILE do .env (separados por ":", relativos ao repositório), como o
# docker compose faz sozinho; vazio = docker-compose.yml. Ex.: deploy/paperless/rede.yml (Ficha 6).
dc() {
  local lista arquivos=() f
  lista="$(valor_env COMPOSE_FILE)"
  [ -n "$lista" ] || lista=docker-compose.yml
  local IFS=:
  for f in $lista; do arquivos+=(-f "$(caminho_docker "$APP/$f")"); done
  unset IFS
  docker compose --project-directory "$(caminho_docker "$APP")" "${arquivos[@]}" \
    --env-file "$(caminho_docker "$ENV_FILE")" "$@"
}

# docker compose quieto; se falhar, mostra as últimas linhas da saída.
dc_quieto() {
  local saida
  if saida="$(dc "$@" 2>&1)"; then return 0; fi
  printf '%s\n' "$saida" | tr -d '\r' | tail -n 20 >&2
  return 1
}

servico_definido() { dc config --services 2>/dev/null | tr -d '\r' | grep -qx "$1"; }

# Imagem do Postgres declarada no compose (usada também para tar/chown como root em data/).
imagem_postgres() {
  grep -E '^[[:space:]]*image:[[:space:]]*postgres:' "$APP/docker-compose.yml" | head -n 1 | awk '{print $2}'
}

# tar de uma pasta de data/ lida como root num container: estado do Tailscale e das sessões
# pode ter dono root ou o uid do container, que o usuário do host não lê.
tar_data_criar() {  # <subpasta de data/> > saída.tar
  docker run --rm -i --user 0 --entrypoint tar -v "$(caminho_docker "$HOME_DIR/data"):/d:ro" \
    "$(imagem_postgres)" -C /d --numeric-owner -cf - "$1"
}

tar_data_extrair() {  # < entrada.tar   (extrai dentro de data/, preservando donos e permissões)
  docker run --rm -i --user 0 --entrypoint tar -v "$(caminho_docker "$HOME_DIR/data"):/d" \
    "$(imagem_postgres)" -C /d --numeric-owner -xpf -
}

chown_data() {  # <uid> <subpasta de data/>
  docker run --rm --user 0 --entrypoint chown -v "$(caminho_docker "$HOME_DIR/data"):/d" \
    "$(imagem_postgres)" -R "$1:$1" "/d/$2"
}

pasta_vazia() { [ ! -d "$1" ] || [ -z "$(ls -A "$1" 2>/dev/null)" ]; }

sha256_de() {  # <arquivo> -> só o hash
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

sha256_conferir() {  # roda dentro da pasta: confere SHA256SUMS
  if command -v sha256sum >/dev/null 2>&1; then sha256sum --quiet -c SHA256SUMS
  else shasum -a 256 --quiet -c SHA256SUMS; fi
}

# --- age: do host, se houver; senão, na imagem deploy/ferramentas ---------------------------

garantir_imagem_ferramentas() {
  docker image inspect "$IMAGEM_FERRAMENTAS" >/dev/null 2>&1 && return 0
  log "construindo a imagem $IMAGEM_FERRAMENTAS (age sem instalar nada no host)"
  docker build -q -t "$IMAGEM_FERRAMENTAS" "$(caminho_docker "$APP/deploy/ferramentas")" >/dev/null \
    || falha "não consegui construir $IMAGEM_FERRAMENTAS."
}

cifrar() {  # <destinatário age1...>  < entrada > saída
  if command -v age >/dev/null 2>&1; then
    age -r "$1"
  else
    garantir_imagem_ferramentas
    docker run --rm -i "$IMAGEM_FERRAMENTAS" age -r "$1"
  fi
}

decifrar() {  # <arquivo de identidade>  < entrada > saída
  local chave="$1"
  if command -v age >/dev/null 2>&1; then
    age -d -i "$chave"
  else
    garantir_imagem_ferramentas
    local usuario=()
    no_windows || usuario=(--user "$(id -u):$(id -g)")
    docker run --rm -i "${usuario[@]}" -v "$(caminho_docker "$(dirname "$chave")"):/chave:ro" \
      "$IMAGEM_FERRAMENTAS" age -d -i "/chave/$(basename "$chave")"
  fi
}

# --- Funnel pela internet ---------------------------------------------------------------------
# O host com Tailscale e MagicDNS resolve o nome .ts.net para o IP da tailnet: o curl nunca passa
# pela internet e dá 401 mesmo com o DNS público vazio (2026-10-23). Por isso o nome é resolvido num
# DNS público (DoH, pelo IP, sem depender do DNS local) e o curl vai ao IP público do Funnel.
DOH_URLS="${VERIFICAR_DOH:-https://1.1.1.1/dns-query https://8.8.8.8/resolve}"

# <host> -> primeiro IPv4 no DNS público. Código 1: o nome não existe; 2: nenhum DoH respondeu.
ip_publico() {
  local host="$1" url resp respondeu=0 ip
  for url in $DOH_URLS; do
    resp="$(curl -s -m 10 -H 'accept: application/dns-json' "$url?name=$host&type=A" | tr -d '\r\n')" || continue
    printf '%s' "$resp" | grep -q '"Status"' || continue
    respondeu=1
    ip="$(printf '%s' "$resp" | grep -oE '"data": ?"[0-9]{1,3}(\.[0-9]{1,3}){3}"' | head -n 1 | grep -oE '[0-9.]{7,15}')"
    [ -n "$ip" ] && { printf '%s\n' "$ip"; return 0; }
  done
  [ "$respondeu" = 1 ] && return 1
  return 2
}

# <url base> -> uma linha para o relatório; código 0 só se <url>/mcp sem token der 401 pela internet.
conferir_funnel_publico() {
  local url="${1%/}" host ip codigo rc
  host="${url#https://}"; host="${host%%/*}"
  ip="$(ip_publico "$host")"; rc=$?
  case "$rc" in
    0) ;;
    1) echo "Funnel: $host não existe no DNS público (depois de reiniciar o Tailscale, pode levar ~20 min)"; return 1 ;;
    *) echo "Funnel: nenhum DNS público respondeu ($DOH_URLS); sem internet?"; return 1 ;;
  esac
  codigo="$(curl -s -o /dev/null -m 20 -w '%{http_code}' --resolve "$host:443:$ip" "$url/mcp" || true)"
  if [ "$codigo" = 401 ]; then
    echo "Funnel pela internet: $url/mcp ($ip) sem token = 401"
  else
    echo "Funnel pela internet: $url/mcp ($ip) sem token = ${codigo:-sem resposta} (esperado 401)"
    return 1
  fi
}

# --- Postgres ---------------------------------------------------------------------------------

esperar_saudavel() {  # <serviço> [segundos]
  local servico="$1" limite="${2:-180}" inicio estado id
  inicio="$(date +%s)"
  while :; do
    id="$(dc ps -q "$servico" 2>/dev/null | tr -d '\r' | head -n 1)"
    if [ -n "$id" ]; then
      estado="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null | tr -d '\r')"
      # "running" só aparece para serviço sem healthcheck.
      case "$estado" in healthy|running) return 0 ;; esac
      [ "$estado" = unhealthy ] && { aviso "$servico está unhealthy."; return 1; }
    fi
    [ $(( $(date +%s) - inicio )) -lt "$limite" ] || { aviso "$servico não ficou saudável em ${limite}s (estado: ${estado:-sem container})."; return 1; }
    sleep 3
  done
}

psql_dono() {  # SQL pela entrada; saída sem alinhamento, colunas separadas por TAB
  dc exec -T postgres sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "	"' \
    | tr -d '\r'
}

# Linhas por tabela do schema public, ordenado: "tabela<TAB>linhas".
contagens() {
  psql_dono <<'SQL'
select c.relname,
       (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from public.%I', c.relname), false, true, '')))[1]::text
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'p')
order by c.relname;
SQL
}

versao_schema() { echo "select version_num from alembic_version" | psql_dono 2>/dev/null | head -n 1; }

tabelas_no_banco() { echo "select count(*) from pg_tables where schemaname = 'public'" | psql_dono; }

# Compara um contagens.tsv com o banco. Tabela nova no banco (migração mais nova) não conta.
conferir_contagens() {  # <contagens.tsv>
  local esperado="$1" atual erros=0 tabela n obtido
  atual="$(contagens)" || { aviso "não consegui contar as linhas."; return 1; }
  while IFS="$(printf '\t')" read -r tabela n; do
    [ -n "$tabela" ] || continue
    obtido="$(printf '%s\n' "$atual" | awk -F'\t' -v t="$tabela" '$1 == t {print $2}')"
    if [ "$obtido" != "$n" ]; then
      aviso "contagem diferente em $tabela: pacote $n, banco ${obtido:-<sem tabela>}"
      erros=$((erros + 1))
    fi
  done < <(tr -d '\r' <"$esperado")
  [ "$erros" -eq 0 ]
}

# --- Retenção dos pacotes: últimos 7 dias e últimas 4 semanas (como restic --keep-daily 7
# --keep-weekly 4): por dia e por semana ISO, fica o pacote mais novo. Só toca em arquivos com o
# nome exato que o exportar cria. O Paperless (paperless/scripts/comum.sh) troca o prefixo e o padrão. ---

PREFIXO_PACOTE=assistente
PADRAO_PACOTE='assistente-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*.tar.age'

semana_iso() {  # AAAAMMDD -> AAAA-SS
  date -d "$1" +%G-%V 2>/dev/null || date -j -f %Y%m%d "$1" +%G-%V
}

# Duas instâncias (ex.: a da Nathalia) com o mesmo BACKUP_DESTINO: a retenção de uma apagaria os pacotes da
# outra, que têm o mesmo nome. A pasta guarda em .instancia o COMPOSE_PROJECT_NAME de quem a usa e recusa outro,
# com ou sem retenção (um pacote avulso também entraria na conta da outra). Só a retenção marca a pasta.
conferir_instancia_da_pasta() {  # <pasta> <instancia> [marcar: 1 ou 0]
  local pasta="$1" instancia="$2" marcar="${3:-1}" marca="$1/.instancia" dona
  [ -n "$instancia" ] || falha "COMPOSE_PROJECT_NAME vazio: não sei de que instância é o backup."
  if [ -f "$marca" ]; then
    dona="$(tr -d '\r\n' <"$marca")"
    [ "$dona" = "$instancia" ] \
      || falha "a pasta $pasta é do backup da instância '$dona', não de '$instancia'. Use outro BACKUP_DESTINO (ex.: $pasta/$instancia)."
  elif [ "$marcar" -eq 1 ]; then
    printf '%s\n' "$instancia" >"$marca" || falha "não gravei $marca."
  fi
}

pacotes_a_apagar() {  # <pasta> [diarios] [semanais] -> nomes, um por linha
  local pasta="$1" diarios="${2:-7}" semanais="${3:-4}" nome dia semana
  local dias_vistos="" semanas_vistas="" n_dias=0 n_semanas=0 fica
  while IFS= read -r nome; do
    [ -n "$nome" ] || continue
    dia="${nome#"$PREFIXO_PACOTE"-}"; dia="${dia%%-*}"
    semana="$(semana_iso "$dia")" || { aviso "data inválida no nome $nome; não apago."; continue; }
    fica=0
    case " $dias_vistos " in
      *" $dia "*) ;;
      *) if [ "$n_dias" -lt "$diarios" ]; then fica=1; n_dias=$((n_dias + 1)); dias_vistos="$dias_vistos $dia"; fi ;;
    esac
    case " $semanas_vistas " in
      *" $semana "*) ;;
      *) if [ "$n_semanas" -lt "$semanais" ]; then fica=1; n_semanas=$((n_semanas + 1)); semanas_vistas="$semanas_vistas $semana"; fi ;;
    esac
    [ "$fica" -eq 1 ] || printf '%s\n' "$nome"
  done < <(cd "$pasta" && ls -1 $PADRAO_PACOTE 2>/dev/null | sort -r)
}
