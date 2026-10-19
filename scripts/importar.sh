#!/usr/bin/env bash
# Sobe o assistente numa máquina nova a partir de um pacote do exportar.sh (docs/MIGRACAO.md).
#
#   scripts/importar.sh <pacote.tar.age> --chave <identidade-age.txt> [opções]
#     --assumir-tailscale  restaura data/tailscale: esta máquina vira o nó TS_NOME da antiga.
#                          Só com a antiga DESLIGADA (as duas juntas com o mesmo estado brigam).
#     --manter-env         usa o .env que já está em <home>, em vez do que veio no pacote.
#
# Ordem: confere o hash do pacote, decifra, confere o SHA256SUMS, põe o .env (ASSISTENTE_HOME
# reescrito para esta máquina), sobe só o Postgres (usuários criados pelo 01-papeis.sh com as
# senhas do .env), restaura o dump, confere a contagem de linhas, roda alembic upgrade head,
# põe vault e sessões no lugar, sobe o resto e chama o verificar.sh. Só termina com 0 se o
# verificar passar.
#
# Nunca sobrescreve: recusa se data/postgres, o banco, o vault ou data/tailscale já têm conteúdo.
# A chave privada do age não é copiada para lugar nenhum.
source "$(dirname "$0")/lib.sh"

PACOTE=""
CHAVE=""
ASSUMIR_TS=0
MANTER_ENV=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --chave) CHAVE="${2:-}"; shift 2 || falha "--chave precisa do arquivo de identidade." ;;
    --assumir-tailscale) ASSUMIR_TS=1; shift ;;
    --manter-env) MANTER_ENV=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) falha "opção desconhecida: $1 (veja --help)" ;;
    *) [ -z "$PACOTE" ] || falha "um pacote só."; PACOTE="$1"; shift ;;
  esac
done
[ -n "$PACOTE" ] || falha "falta o pacote (veja --help)."
[ -n "$CHAVE" ] || falha "falta --chave <identidade-age.txt>."
PACOTE="$(absoluto "$PACOTE")"
CHAVE="$(absoluto "$CHAVE")"
[ -s "$PACOTE" ] || falha "pacote inexistente ou vazio: $PACOTE"
[ -s "$CHAVE" ] || falha "chave inexistente ou vazia: $CHAVE"

descobrir_home

# --- 1. Nada a sobrescrever --------------------------------------------------------------------
pasta_vazia "$HOME_DIR/data/postgres" \
  || falha "$HOME_DIR/data/postgres já tem dados. O importar só sobe em pasta vazia; não apago nada."
if [ "$ASSUMIR_TS" -eq 1 ]; then
  pasta_vazia "$HOME_DIR/data/tailscale" || falha "$HOME_DIR/data/tailscale já tem uma identidade; não sobrescrevo."
fi
if [ -f "$ENV_FILE" ] && [ "$MANTER_ENV" -eq 0 ]; then
  falha "já existe $ENV_FILE. Use --manter-env para usá-lo, ou tire-o daí para usar o do pacote."
fi
[ "$MANTER_ENV" -eq 0 ] || [ -f "$ENV_FILE" ] || falha "--manter-env sem $ENV_FILE."

if [ -f "$PACOTE.sha256" ]; then
  [ "$(sha256_de "$PACOTE")" = "$(awk '{print $1}' "$PACOTE.sha256")" ] \
    || falha "o hash do pacote não bate com $PACOTE.sha256: cópia corrompida?"
  log "hash do pacote ok"
else
  aviso "sem $PACOTE.sha256 ao lado; sigo, e o SHA256SUMS de dentro confere cada arquivo."
fi

umask 077
mkdir -p "$HOME_DIR/backups" || falha "não consegui criar $HOME_DIR/backups."
TMP="$HOME_DIR/backups/.tmp-importar-$$"
trap 'codigo=$?; rm -rf "$TMP"; exit $codigo' EXIT
trap 'exit 130' INT TERM
mkdir -p "$TMP"

# --- 2. Decifrar e conferir ---------------------------------------------------------------------
log "decifrando"
decifrar "$CHAVE" <"$PACOTE" | tar -C "$TMP" -xf - || falha "não consegui decifrar ou abrir o pacote (chave certa?)."
[ -f "$TMP/SHA256SUMS" ] || falha "pacote sem SHA256SUMS."
(cd "$TMP" && sha256_conferir) || falha "SHA256SUMS não confere: pacote corrompido."
for f in banco.dump contagens.tsv env manifesto.json; do
  [ -s "$TMP/$f" ] || falha "pacote sem $f."
done
log "arquivos conferidos: $(cd "$TMP" && ls | tr '\n' ' ')"
if [ -f "$TMP/vault.tar" ] && ! pasta_vazia "$HOME_DIR/vault"; then
  falha "$HOME_DIR/vault já tem conteúdo e o pacote traz um vault; não sobrescrevo."
fi

# --- 3. .env -----------------------------------------------------------------------------------
if [ "$MANTER_ENV" -eq 0 ]; then
  NOVO_HOME="$(caminho_docker "$HOME_DIR")"
  # Só a linha ASSISTENTE_HOME muda; o resto é igual ao da máquina antiga.
  awk -v h="$NOVO_HOME" 'BEGIN{feito=0} /^[[:space:]]*ASSISTENTE_HOME=/{print "ASSISTENTE_HOME=" h; feito=1; next} {print} END{if(!feito) print "ASSISTENTE_HOME=" h}' \
    "$TMP/env" | tr -d '\r' >"$ENV_FILE" || falha "não consegui gravar $ENV_FILE."
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  log ".env do pacote em $ENV_FILE (ASSISTENTE_HOME=$NOVO_HOME)"
fi
conferir_env

# --- 4. Pastas e Postgres ---------------------------------------------------------------------
mkdir -p "$HOME_DIR/data/postgres" "$HOME_DIR/data/sessoes/oauth" "$HOME_DIR/data/tailscale" \
  "$HOME_DIR/vault" "$HOME_DIR/logs" || falha "não consegui criar as pastas de $HOME_DIR."
if servico_definido paperless; then
  falha "o compose tem Paperless, e a importação dele (document_importer) ainda não foi implementada."
fi

log "construindo as imagens"
dc_quieto build || falha "docker compose build falhou."
log "subindo só o Postgres"
dc_quieto up -d postgres || falha "não consegui subir o Postgres."
esperar_saudavel postgres 300 || falha "o Postgres não ficou saudável (docker compose logs postgres)."
[ "$(tabelas_no_banco)" = "0" ] || falha "o banco novo já tem tabelas; não restauro por cima."

log "restaurando o banco"
dc exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction' \
  <"$TMP/banco.dump" || falha "pg_restore falhou (nada ficou pela metade: --single-transaction)."
conferir_contagens "$TMP/contagens.tsv" || falha "contagem de linhas não bate com o pacote."
log "contagens iguais às do pacote ($(wc -l <"$TMP/contagens.tsv" | tr -d ' ') tabelas)"

log "alembic upgrade head"
dc_quieto run --rm --no-deps migracao || falha "a migração falhou (docker compose run --rm migracao)."
log "schema: pacote $(grep -o '"schema": "[^"]*"' "$TMP/manifesto.json" | cut -d'"' -f4), agora $(versao_schema)"

# --- 5. Vault, sessões e Tailscale -------------------------------------------------------------
if [ -f "$TMP/vault.tar" ]; then
  tar -C "$HOME_DIR" -xf "$TMP/vault.tar" || falha "não consegui extrair o vault."
  log "vault no lugar"
fi
if [ -f "$TMP/sessoes.tar" ]; then
  tar_data_extrair <"$TMP/sessoes.tar" || falha "não consegui extrair data/sessoes."
  log "sessões no lugar"
fi
chown_data "$UID_SERVIDOR" sessoes/oauth || aviso "não consegui dar data/sessoes/oauth ao uid $UID_SERVIDOR."
if [ -f "$TMP/tailscale.tar" ]; then
  if [ "$ASSUMIR_TS" -eq 1 ]; then
    tar_data_extrair <"$TMP/tailscale.tar" || falha "não consegui extrair data/tailscale."
    log "identidade do Tailscale assumida (a máquina antiga precisa estar desligada)"
  else
    log "identidade do Tailscale NÃO restaurada: esta máquina entra como nó novo (veja docs/MIGRACAO.md, passo 5)."
  fi
fi

# --- 6. Subir e verificar ---------------------------------------------------------------------
log "subindo tudo"
dc_quieto up -d || falha "docker compose up -d falhou."
esperar_saudavel servidor 300 || falha "o servidor não ficou saudável (docker compose logs servidor)."

GUARDA="$HOME_DIR/backups/importado-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$GUARDA" && cp "$TMP/manifesto.json" "$TMP/contagens.tsv" "$GUARDA/"
log "manifesto guardado em $GUARDA"
bash "$APP/scripts/verificar.sh" --contagens "$GUARDA/contagens.tsv" || falha "verificar.sh falhou: a importação não está pronta."
log "importação concluída."
