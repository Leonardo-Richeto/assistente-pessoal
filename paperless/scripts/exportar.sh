#!/usr/bin/env bash
# Backup do Paperless único (PLANO 7.3): um arquivo paperless-AAAAMMDD-HHMM.tar.age, cifrado com a
# chave PÚBLICA do age (AGE_DESTINATARIO no .env, a mesma do assistente). O backup do assistente
# (scripts/exportar.sh) não leva documentos: este é o único que leva.
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/exportar.sh             # em BACKUP_DESTINO
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/exportar.sh --retencao  # 7 diários e 4 semanais
#   ... --destino <pasta>                                                   # outra pasta
#
# Conteúdo do pacote:
#   export.tar      saída do document_exporter (documentos, usuários, donos, permissões, workflows)
#   contagens.tsv   documentos por dono, notas, tags... (gestao.py contar), para o importar conferir
#   env             o .env (senhas do banco e a SECRET_KEY)
#   manifesto.json  data, máquina, commit, versão do Paperless, arquivos e contagens
#   SHA256SUMS      hash de cada arquivo acima
# O Paperless fica de pé durante a exportação. O texto aberto só existe em export/ e na pasta
# temporária, apagados no fim (sucesso ou erro).
source "$(dirname "$0")/comum.sh"

DESTINO=""
RETENCAO=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destino) DESTINO="${2:-}"; shift 2 || falha "--destino precisa de uma pasta." ;;
    --retencao) RETENCAO=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) falha "opção desconhecida: $1 (veja --help)" ;;
  esac
done

descobrir_home
conferir_env
DESTINATARIO="$(valor_env AGE_DESTINATARIO)"
case "$DESTINATARIO" in
  age1*) ;;
  *) falha "AGE_DESTINATARIO vazio ou inválido no .env (precisa ser a chave pública age1...)." ;;
esac
[ -n "$DESTINO" ] || DESTINO="$(valor_env BACKUP_DESTINO)"
[ -n "$DESTINO" ] || DESTINO="$HOME_DIR/backups"
DESTINO="$(absoluto "$DESTINO")"
umask 077
mkdir -p "$DESTINO" "$HOME_DIR/backups" || falha "não consegui criar $DESTINO."

esperar_saudavel webserver 300 || falha "o webserver não está saudável."

TMP="$HOME_DIR/backups/.tmp-exportar-$$"
SUB="pacote-$$"
limpar() {
  local codigo=$?
  dc exec -T webserver rm -rf "/usr/src/paperless/export/$SUB" >/dev/null 2>&1
  rm -rf "$TMP"
  rm -f "${PARCIAL:-}"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM
mkdir -p "$TMP" || falha "não consegui criar $TMP."

# Contagem antes e depois do exporter: documento que entra no meio (pasta de consumo) muda a conta,
# e aí o pacote não teria contagens iguais ao export. Nesse caso, falha e o próximo backup pega tudo.
gestao contar >"$TMP/contagens-antes.tsv" || falha "não consegui contar os documentos."
log "document_exporter"
dc_quieto exec -T -u paperless webserver mkdir -p "/usr/src/paperless/export/$SUB" \
  || falha "não consegui criar export/$SUB no webserver."
dc_quieto exec -T webserver document_exporter "../export/$SUB" --no-progress-bar \
  || falha "document_exporter falhou."
dc exec -T webserver tar -C /usr/src/paperless/export -cf - "$SUB" >"$TMP/export.tar" \
  || falha "tar do export falhou."
gestao contar >"$TMP/contagens.tsv" || falha "não consegui contar os documentos."
[ -s "$TMP/contagens.tsv" ] || falha "contagem vazia."
cmp -s "$TMP/contagens-antes.tsv" "$TMP/contagens.tsv" \
  || falha "os documentos mudaram durante a exportação (consumo no meio); rode de novo."
rm -f "$TMP/contagens-antes.tsv"
cp "$ENV_FILE" "$TMP/env" || falha "não consegui copiar o .env."

VERSAO="$(dc exec -T webserver python3 -c 'import sys; sys.path.insert(0, "/usr/src/paperless/src"); from paperless.version import __full_version_str__ as v; print(v)' 2>/dev/null | tr -d '\r')"
COMMIT="$(git -C "$(caminho_docker "$APP")" rev-parse HEAD 2>/dev/null || echo desconhecido)"
[ -z "$(git -C "$(caminho_docker "$APP")" status --porcelain 2>/dev/null)" ] || COMMIT="$COMMIT+alterado"
CARIMBO="$(date +%Y%m%d-%H%M)"
NOME="paperless-$CARIMBO.tar.age"
[ ! -e "$DESTINO/$NOME" ] || { CARIMBO="$(date +%Y%m%d-%H%M%S)"; NOME="paperless-$CARIMBO.tar.age"; }

json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
{
  printf '{\n  "formato": 1,\n'
  printf '  "criado_em": "%s",\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf '  "maquina": "%s",\n' "$(json "$(hostname 2>/dev/null || echo desconhecida)")"
  printf '  "commit": "%s",\n' "$(json "$COMMIT")"
  printf '  "paperless": "%s",\n' "$(json "${VERSAO:-desconhecida}")"
  printf '  "pasta_export": "%s",\n' "$SUB"
  printf '  "arquivos": {'
  sep=""
  for f in "$TMP"/*; do
    [ "$(basename "$f")" = manifesto.json ] && continue
    printf '%s\n    "%s": {"bytes": %s, "sha256": "%s"}' "$sep" "$(basename "$f")" "$(wc -c <"$f" | tr -d ' ')" "$(sha256_de "$f")"
    sep=","
  done
  printf '\n  },\n  "contagens": {'
  sep=""
  while IFS="$(printf '\t')" read -r t n; do
    printf '%s\n    "%s": %s' "$sep" "$(json "$t")" "$n"
    sep=","
  done <"$TMP/contagens.tsv"
  printf '\n  }\n}\n'
} >"$TMP/manifesto.json"
SOMAS="$(cd "$TMP" && for f in *; do printf '%s  %s\n' "$(sha256_de "$f")" "$f"; done)" \
  || falha "não consegui calcular os hashes."
printf '%s\n' "$SOMAS" >"$TMP/SHA256SUMS" || falha "não consegui gravar SHA256SUMS."

PARCIAL="$DESTINO/$NOME.parcial"
log "cifrando para $DESTINO/$NOME"
tar -C "$TMP" -cf - . | cifrar "$DESTINATARIO" >"$PARCIAL" || falha "tar ou age falhou."
[ -s "$PARCIAL" ] || falha "o pacote saiu vazio."
mv "$PARCIAL" "$DESTINO/$NOME" || falha "não consegui renomear o pacote."
PARCIAL=""
printf '%s  %s\n' "$(sha256_de "$DESTINO/$NOME")" "$NOME" >"$DESTINO/$NOME.sha256"
log "feito: $DESTINO/$NOME ($(wc -c <"$DESTINO/$NOME" | tr -d ' ') bytes; $(awk -F'\t' '$1=="documentos"{print $2}' "$TMP/contagens.tsv") documentos; Paperless ${VERSAO:-?})"

if [ "$RETENCAO" -eq 1 ]; then
  while IFS= read -r velho; do
    [ -n "$velho" ] || continue
    rm -f -- "$DESTINO/$velho" "$DESTINO/$velho.sha256" && log "apagado pela retenção (7 diários, 4 semanais): $velho"
  done < <(pacotes_a_apagar "$DESTINO" 7 4)
fi
exit 0
