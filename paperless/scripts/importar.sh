#!/usr/bin/env bash
# Restaura um pacote do paperless/scripts/exportar.sh num PAPERLESS_HOME novo (máquina nova ou ensaio).
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/importar.sh <pacote.tar.age> --chave <identidade-age.txt>
#
# 1. decifra numa pasta temporária e confere o SHA256SUMS;
# 2. recusa se data/postgres ou data/media já têm algo (o document_importer exige instalação vazia);
# 3. sem .env no destino, usa o do pacote, com o PAPERLESS_HOME trocado pela pasta de destino;
# 4. sobe sem criar o admin (ele vem no pacote), roda o document_importer e confere as contagens
#    (documentos por dono, notas, tags...) com as do pacote;
# 5. roda a conferência da Ficha 6.
source "$(dirname "$0")/comum.sh"

PACOTE="" CHAVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
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
pasta_vazia "$HOME_DIR/data/postgres" || falha "$HOME_DIR/data/postgres não está vazio: importe só numa instalação nova."
pasta_vazia "$HOME_DIR/data/media" || falha "$HOME_DIR/data/media não está vazio: importe só numa instalação nova."
mkdir -p "$HOME_DIR" || falha "não consegui criar $HOME_DIR."

umask 077
# No mesmo disco dos dados, não em /tmp (no Debian, /tmp é RAM): o export decifrado tem os documentos abertos.
TMP="$HOME_DIR/.tmp-importar-$$"
mkdir -p "$TMP" || falha "não consegui criar $TMP."
SUB=""
limpar() {
  local codigo=$?
  [ -n "$SUB" ] && dc exec -T webserver rm -rf "/usr/src/paperless/export/$SUB" >/dev/null 2>&1
  rm -rf "$TMP"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM

log "decifrando $(basename "$PACOTE")"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$TMP" -xf - || falha "não consegui decifrar ou abrir o pacote."
(cd "$TMP" && sha256_conferir) || falha "SHA256SUMS não confere."
log "SHA256SUMS confere"
grep -E '"(criado_em|maquina|paperless|commit)"' "$TMP/manifesto.json" | sed 's/^ */  /'
SUB="$(sed -n 's/.*"pasta_export": "\([^"]*\)".*/\1/p' "$TMP/manifesto.json")"
[[ "$SUB" =~ ^pacote-[0-9]+$ ]] || falha "manifesto sem pasta_export válida."

if [ ! -f "$ENV_FILE" ]; then
  log "sem .env no destino: uso o do pacote, com PAPERLESS_HOME=$HOME_DIR"
  # Pacote de antes de 2026-10-24 tem REDE_ESPOSA: a variável virou REDE_NATHALIA (Ficha 7).
  sed -e "s|^PAPERLESS_HOME=.*|PAPERLESS_HOME=$(caminho_docker "$HOME_DIR")|" \
      -e "s|^REDE_ESPOSA=assistente-esposa-paperless$|REDE_NATHALIA=assistente-nathalia-paperless|" \
      -e "s|^REDE_ESPOSA=|REDE_NATHALIA=|" \
    "$TMP/env" >"$ENV_FILE" \
    || falha "não consegui gravar $ENV_FILE."
  chmod 600 "$ENV_FILE"
fi
conferir_env
[[ " $(valor_env USUARIOS) " != *" esposa "* ]] || aviso "pacote de antes de 2026-10-24 (usuário esposa): depois de \
importar, troque esposa por nathalia em USUARIOS no $ENV_FILE e rode paperless/scripts/renomear.sh esposa nathalia."
criar_pastas

log "subindo sem criar o admin (ele vem no pacote)"
PAPERLESS_ADMIN_USER="" PAPERLESS_ADMIN_PASSWORD="" dc_quieto up -d || falha "docker compose up falhou."
esperar_saudavel webserver 600 || falha "o webserver não ficou saudável."

log "document_importer"
dc exec -T webserver tar -C /usr/src/paperless/export -xf - <"$TMP/export.tar" || falha "não consegui copiar o export."
dc exec -T webserver chown -R paperless:paperless "/usr/src/paperless/export/$SUB" || falha "chown do export falhou."
dc_quieto exec -T webserver document_importer "../export/$SUB" --no-progress-bar || falha "document_importer falhou."

gestao contar >"$TMP/contagens-destino.tsv" || falha "não consegui contar os documentos."
diff <(tr -d '\r' <"$TMP/contagens.tsv") "$TMP/contagens-destino.tsv" >&2 \
  || falha "as contagens não batem com as do pacote."
log "contagens iguais às do pacote:"
sed 's/^/  /' "$TMP/contagens-destino.tsv"

bash "$(dirname "$0")/conferir.sh" || falha "a conferência da Ficha 6 achou problema depois da importação."
log "importação ok."
log "os tokens da API não vêm no pacote (o document_exporter não exporta): rode paperless/scripts/token.sh <pessoa>"
log "e troque o PAPERLESS_API_KEY no .env de cada instância do assistente (docs/MIGRACAO.md)."
