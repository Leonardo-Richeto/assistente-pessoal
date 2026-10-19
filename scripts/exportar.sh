#!/usr/bin/env bash
# Gera o pacote de backup/migração: um único arquivo assistente-AAAAMMDD-HHMM.tar.age, cifrado
# com a chave PÚBLICA do age (AGE_DESTINATARIO no .env). Mesmo script para o backup diário e
# para a migração (docs/MIGRACAO.md).
#
#   scripts/exportar.sh                    # pacote em BACKUP_DESTINO (ou <home>/backups)
#   scripts/exportar.sh --destino <pasta>  # outra pasta (ex.: HD externo)
#   scripts/exportar.sh --congelar         # migração: deixa tudo parado, menos o Postgres
#   scripts/exportar.sh --retencao         # backup diário: mantém 7 diários e 4 semanais
#
# Para os serviços que gravam (servidor, Tailscale e o que vier), com o Postgres ligado, e:
#   banco.dump      pg_dump -Fc (tabelas, dados, índices, sequences, GRANTs, alembic_version)
#   contagens.tsv   linhas por tabela, para o importar conferir
#   vault.tar       <home>/vault inteiro, com o .git
#   sessoes.tar     <home>/data/sessoes (login OAuth e, no futuro, outras sessões)
#   tailscale.tar   <home>/data/tailscale (identidade do nó; o importar só usa se pedirem)
#   env             o .env
#   manifesto.json  commit, versão do schema, data, máquina, arquivos e contagens
#   SHA256SUMS      hash de cada arquivo acima
# Nunca copia data/postgres. Sem a chave privada, nada do pacote é legível.
# Os serviços voltam ao estado anterior no fim, mesmo com erro (menos com --congelar).
source "$(dirname "$0")/lib.sh"

DESTINO=""
CONGELAR=0
RETENCAO=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destino) DESTINO="${2:-}"; shift 2 || falha "--destino precisa de uma pasta." ;;
    --congelar) CONGELAR=1; shift ;;
    --retencao) RETENCAO=1; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
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
if servico_definido paperless; then
  falha "o compose tem Paperless, e a exportação dele (document_exporter) ainda não foi implementada. Veja docs/MIGRACAO.md."
fi

[ -n "$DESTINO" ] || DESTINO="$(valor_env BACKUP_DESTINO)"
[ -n "$DESTINO" ] || DESTINO="$HOME_DIR/backups"
DESTINO="$(absoluto "$DESTINO")"
umask 077
mkdir -p "$DESTINO" "$HOME_DIR/backups" || falha "não consegui criar $DESTINO."

# Texto aberto só aqui, no mesmo disco dos dados, e apagado no fim (sucesso ou erro).
TMP="$HOME_DIR/backups/.tmp-exportar-$$"
PARADOS=()
limpar() {
  local codigo=$?
  rm -rf "$TMP"
  rm -f "${PARCIAL:-}"
  if [ "${#PARADOS[@]}" -gt 0 ]; then
    if [ "$CONGELAR" -eq 1 ] && [ "$codigo" -eq 0 ]; then
      log "congelado: ficam parados ${PARADOS[*]}. Nada mais é gravado nesta máquina."
    else
      log "religando: ${PARADOS[*]}"
      dc_quieto up -d --no-build "${PARADOS[@]}" || aviso "não consegui religar ${PARADOS[*]}; rode: docker compose up -d"
    fi
  fi
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM
mkdir -p "$TMP" || falha "não consegui criar $TMP."

# --- 1. Postgres de pé; o resto parado ---------------------------------------------------------
dc_quieto up -d --no-build postgres || falha "não consegui subir o Postgres (docker compose up -d postgres)."
esperar_saudavel postgres || falha "o Postgres não está saudável."

while IFS= read -r s; do
  [ -n "$s" ] && [ "$s" != postgres ] && PARADOS+=("$s")
done < <(dc ps --status running --services 2>/dev/null | tr -d '\r')
if [ "${#PARADOS[@]}" -gt 0 ]; then
  log "parando quem grava: ${PARADOS[*]}"
  dc_quieto stop "${PARADOS[@]}" || falha "não consegui parar ${PARADOS[*]}."
fi

# --- 2. Banco ------------------------------------------------------------------------------------
log "pg_dump"
dc exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >"$TMP/banco.dump" \
  || falha "pg_dump falhou."
[ -s "$TMP/banco.dump" ] || falha "o dump saiu vazio."
ITENS="$(dc exec -T postgres pg_restore --list <"$TMP/banco.dump" 2>/dev/null | grep -c ' TABLE DATA ')"
[ "${ITENS:-0}" -ge 1 ] || falha "pg_restore --list não achou dados de tabela no dump."
contagens >"$TMP/contagens.tsv" || falha "não consegui contar as linhas."
[ -s "$TMP/contagens.tsv" ] || falha "contagem vazia: o banco não tem tabelas?"
SCHEMA="$(versao_schema)"
[ -n "$SCHEMA" ] || falha "sem alembic_version no banco: a migração nunca rodou?"

# --- 3. Arquivos --------------------------------------------------------------------------------
if ! pasta_vazia "$HOME_DIR/vault"; then
  log "vault"
  tar -C "$HOME_DIR" -cf "$TMP/vault.tar" vault || falha "tar do vault falhou."
fi
for sub in sessoes tailscale; do
  if ! pasta_vazia "$HOME_DIR/data/$sub"; then
    log "data/$sub"
    tar_data_criar "$sub" >"$TMP/$sub.tar" || falha "tar de data/$sub falhou."
  fi
done
cp "$ENV_FILE" "$TMP/env" || falha "não consegui copiar o .env."

# --- 4. Manifesto e hashes -------------------------------------------------------------------
COMMIT="$(git -C "$(caminho_docker "$APP")" rev-parse HEAD 2>/dev/null || echo desconhecido)"
[ -z "$(git -C "$(caminho_docker "$APP")" status --porcelain 2>/dev/null)" ] || COMMIT="$COMMIT+alterado"
CARIMBO="$(date +%Y%m%d-%H%M)"
NOME="assistente-$CARIMBO.tar.age"
[ ! -e "$DESTINO/$NOME" ] || { CARIMBO="$(date +%Y%m%d-%H%M%S)"; NOME="assistente-$CARIMBO.tar.age"; }

json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
{
  printf '{\n  "formato": 1,\n'
  printf '  "criado_em": "%s",\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf '  "maquina": "%s",\n' "$(json "$(hostname 2>/dev/null || echo desconhecida)")"
  printf '  "commit": "%s",\n' "$(json "$COMMIT")"
  printf '  "schema": "%s",\n' "$(json "$SCHEMA")"
  printf '  "arquivos": {'
  sep=""
  for f in "$TMP"/*; do
    [ "$(basename "$f")" = manifesto.json ] && continue  # o próprio arquivo, ainda sendo escrito
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

# --- 5. Pacote cifrado ---------------------------------------------------------------------------
PARCIAL="$DESTINO/$NOME.parcial"
log "cifrando para $DESTINO/$NOME"
tar -C "$TMP" -cf - . | cifrar "$DESTINATARIO" >"$PARCIAL" || falha "tar ou age falhou."
[ -s "$PARCIAL" ] || falha "o pacote saiu vazio."
mv "$PARCIAL" "$DESTINO/$NOME" || falha "não consegui renomear o pacote."
PARCIAL=""
printf '%s  %s\n' "$(sha256_de "$DESTINO/$NOME")" "$NOME" >"$DESTINO/$NOME.sha256"
log "feito: $DESTINO/$NOME ($(wc -c <"$DESTINO/$NOME" | tr -d ' ') bytes; schema $SCHEMA; commit ${COMMIT:0:12})"

# --- 6. Retenção ---------------------------------------------------------------------------------
if [ "$RETENCAO" -eq 1 ]; then
  while IFS= read -r velho; do
    [ -n "$velho" ] || continue
    rm -f -- "$DESTINO/$velho" "$DESTINO/$velho.sha256" && log "apagado pela retenção (7 diários, 4 semanais): $velho"
  done < <(pacotes_a_apagar "$DESTINO" 7 4)
fi
exit 0
