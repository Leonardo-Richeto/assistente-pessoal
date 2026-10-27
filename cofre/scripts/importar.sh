#!/usr/bin/env bash
# Restaura um pacote do cofre/scripts/exportar.sh num COFRE_HOME novo (máquina nova ou ensaio).
#
#   COFRE_HOME=/srv/cofre cofre/scripts/importar.sh <pacote.tar.age> --chave <identidade-age.txt>
#
# 1. decifra numa pasta temporária e confere o SHA256SUMS;
# 2. recusa se data/vaultwarden já tem algo (não mistura cofres);
# 3. sem .env no destino, usa o do pacote, com o COFRE_HOME trocado pela pasta de destino;
# 4. põe os arquivos e o banco no lugar, confere as contagens com as do pacote e sobe com o cadastro fechado;
# 5. roda a conferência da Ficha 11.
# A identidade do Tailscale não vem no pacote: na máquina nova, o nó entra com uma TS_AUTHKEY nova.
source "$(dirname "$0")/comum.sh"

PACOTE="" CHAVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) falha "opção desconhecida: $1 (veja --help)" ;;
    *) PACOTE="$1"; shift ;;
  esac
done
[ -n "$PACOTE" ] || falha "falta o pacote (veja --help)."
[ -n "$CHAVE" ] || falha "falta --chave <identidade-age.txt>."
PACOTE="$(absoluto "$PACOTE")"; CHAVE="$(absoluto "$CHAVE")"
[ -f "$PACOTE" ] || falha "pacote não encontrado: $PACOTE"
[ -f "$CHAVE" ] || falha "identidade não encontrada: $CHAVE"

descobrir_home
pasta_vazia "$DADOS" || falha "$DADOS não está vazio: importe só numa instalação nova."
mkdir -p "$HOME_DIR" || falha "não consegui criar $HOME_DIR."

umask 077
limpar_sobras
# No mesmo disco dos dados, não em /tmp (no Debian, /tmp é RAM).
TMP="$HOME_DIR/.tmp-importar-$$"
mkdir -p "$TMP" || falha "não consegui criar $TMP."
limpar() {
  local codigo=$?
  rm -rf "$TMP"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM

log "decifrando $(basename "$PACOTE")"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$TMP" -xf - || falha "não consegui decifrar ou abrir o pacote."
(cd "$TMP" && sha256_conferir) || falha "SHA256SUMS não confere."
log "SHA256SUMS confere"
grep -E '"(criado_em|maquina|imagem|commit)"' "$TMP/manifesto.json" | sed 's/^ */  /'

if [ ! -f "$ENV_FILE" ]; then
  log "sem .env no destino: uso o do pacote, com COFRE_HOME=$HOME_DIR e o dono dos arquivos desta máquina"
  sed -e "s|^COFRE_HOME=.*|COFRE_HOME=$(caminho_docker "$HOME_DIR")|" \
      -e "s|^COFRE_UID=.*|COFRE_UID=$(id -u)|" -e "s|^COFRE_GID=.*|COFRE_GID=$(id -g)|" "$TMP/env" >"$ENV_FILE" \
    || falha "não consegui gravar $ENV_FILE."
  chmod 600 "$ENV_FILE"
fi
conferir_env
criar_pastas

tar -C "$DADOS" -xf "$TMP/vaultwarden.tar" || falha "não consegui extrair os arquivos do cofre."
cp "$TMP/db.sqlite3" "$DADOS/db.sqlite3" || falha "não consegui pôr o banco no lugar."
contar "$DADOS/db.sqlite3" >"$TMP/contagens-destino.tsv" || falha "não consegui contar as tabelas."
diff <(tr -d '\r' <"$TMP/contagens.tsv") "$TMP/contagens-destino.tsv" >&2 || falha "as contagens não batem com as do pacote."

log "subindo com o cadastro fechado"
SIGNUPS_ALLOWED=false subir
log "contagens iguais às do pacote:"
sed 's/^/  /' "$TMP/contagens-destino.tsv" | grep -E '^  (users|ciphers|folders|devices|twofactor)	' || true
bash "$(dirname "$0")/conferir.sh" || falha "a conferência da Ficha 11 achou problema depois da importação."
log "importação ok."
