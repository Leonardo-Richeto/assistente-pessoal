#!/usr/bin/env bash
# Backup do cofre (Ficha 11, regra 7): um arquivo cofre-AAAAMMDD-HHMM.tar.age, cifrado com a chave PÚBLICA do age
# (AGE_DESTINATARIO no .env, a mesma do assistente). O cofre fica de pé: o banco sai pela API de backup do SQLite.
#
#   COFRE_HOME=/srv/cofre cofre/scripts/exportar.sh             # em BACKUP_DESTINO
#   COFRE_HOME=/srv/cofre cofre/scripts/exportar.sh --retencao  # 7 diários e 4 semanais
#   ... --destino <pasta>                                       # outra pasta
#
# Conteúdo do pacote:
#   vaultwarden.tar  data/vaultwarden sem o banco vivo (chaves RSA, anexos, sends, config.json)
#   db.sqlite3       cópia consistente do banco
#   contagens.tsv    linhas por tabela do banco, para o importar conferir
#   env              o .env (sem segredo do cofre; a TS_AUTHKEY já deve estar vazia)
#   manifesto.json   data, máquina, commit, versão da imagem, arquivos e contagens
#   SHA256SUMS       hash de cada arquivo acima
# O texto aberto só existe na pasta temporária, apagada no fim (sucesso ou erro).
source "$(dirname "$0")/comum.sh"

DESTINO=""
RETENCAO=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destino) DESTINO="${2:-}"; shift 2 || falha "--destino precisa de uma pasta." ;;
    --retencao) RETENCAO=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
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
conferir_instancia_da_pasta "$DESTINO" "$(valor_env COMPOSE_PROJECT_NAME)" "$RETENCAO"
[ -f "$DADOS/db.sqlite3" ] || falha "sem $DADOS/db.sqlite3: o cofre já subiu alguma vez?"

limpar_sobras
TMP="$HOME_DIR/backups/.tmp-exportar-$$"
limpar() {
  local codigo=$?
  rm -rf "$TMP"
  rm -f "${PARCIAL:-}"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM
mkdir -p "$TMP" || falha "não consegui criar $TMP."

log "copiando o banco (com o cofre de pé)"
copiar_banco "$TMP/db.sqlite3"
contar "$TMP/db.sqlite3" >"$TMP/contagens.tsv" || falha "não consegui contar as tabelas."
grep -q "^users	" "$TMP/contagens.tsv" || falha "a cópia do banco não tem a tabela users."
tar -C "$DADOS" --exclude='./db.sqlite3' --exclude='./db.sqlite3-wal' --exclude='./db.sqlite3-shm' \
  --exclude='./tmp' --exclude='./icon_cache' -cf "$TMP/vaultwarden.tar" . || falha "tar de data/vaultwarden falhou."
cp "$ENV_FILE" "$TMP/env" || falha "não consegui copiar o .env."
[ -z "$(valor_env TS_AUTHKEY)" ] || aviso "TS_AUTHKEY ainda preenchida no .env: apague depois da primeira subida."

IMAGEM="$(grep -E '^[[:space:]]*image:[[:space:]]*vaultwarden/' "$COFRE_APP/docker-compose.yml" | head -n 1 | awk '{print $2}')"
COMMIT="$(git -C "$(caminho_docker "$APP")" rev-parse HEAD 2>/dev/null || echo desconhecido)"
[ -z "$(git -C "$(caminho_docker "$APP")" status --porcelain 2>/dev/null)" ] || COMMIT="$COMMIT+alterado"
CARIMBO="$(date +%Y%m%d-%H%M)"
NOME="cofre-$CARIMBO.tar.age"
[ ! -e "$DESTINO/$NOME" ] || { CARIMBO="$(date +%Y%m%d-%H%M%S)"; NOME="cofre-$CARIMBO.tar.age"; }

json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
{
  printf '{\n  "formato": 1,\n'
  printf '  "criado_em": "%s",\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf '  "maquina": "%s",\n' "$(json "$(hostname 2>/dev/null || echo desconhecida)")"
  printf '  "commit": "%s",\n' "$(json "$COMMIT")"
  printf '  "imagem": "%s",\n' "$(json "${IMAGEM:-desconhecida}")"
  printf '  "arquivos": {'
  sep=""
  for f in "$TMP"/*; do
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
log "feito: $DESTINO/$NOME ($(wc -c <"$DESTINO/$NOME" | tr -d ' ') bytes; $(awk -F'\t' '$1=="users"{print $2}' "$TMP/contagens.tsv") contas, $(awk -F'\t' '$1=="ciphers"{print $2}' "$TMP/contagens.tsv") itens)"

if [ "$RETENCAO" -eq 1 ]; then
  while IFS= read -r velho; do
    [ -n "$velho" ] || continue
    rm -f -- "$DESTINO/$velho" "$DESTINO/$velho.sha256" && log "apagado pela retenção (7 diários, 4 semanais): $velho"
  done < <(pacotes_a_apagar "$DESTINO" 7 4)
fi
exit 0
