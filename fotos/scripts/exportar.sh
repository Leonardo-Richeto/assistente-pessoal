#!/usr/bin/env bash
# Backup das fotos (Ficha 17, regra 7), cifrado com a chave PÚBLICA do age (AGE_DESTINATARIO, a mesma do assistente).
# O Immich fica de pé. Duas partes em BACKUP_DESTINO:
#
#   fotos-AAAAMMDD-HHMM.tar.age  o banco: o dump mais novo que o próprio Immich faz às 02:00 (immich-config.json,
#                                "backup.database"), o .env, o índice dos arquivos e o manifesto. 7 diários e 4
#                                semanais com --retencao.
#   arquivos/<caminho>.age       um arquivo cifrado por original (library, upload, profile). Incremental: só cifra o
#                                que ainda não está lá. Miniaturas e vídeos convertidos ficam de fora: o Immich refaz.
#   removidas/AAAA-MM-DD/...     o que sumiu da biblioteca vai para cá e fica 30 dias.
#
#   FOTOS_HOME=/srv/fotos fotos/scripts/exportar.sh             # em BACKUP_DESTINO
#   FOTOS_HOME=/srv/fotos fotos/scripts/exportar.sh --retencao  # e apaga pela retenção
#   ... --destino <pasta>                                       # outra pasta
#
# Precisa do age no host (o preparar_host.sh instala): um "docker run" por arquivo seria lento demais.
source "$(dirname "$0")/comum.sh"

PREFIXO_PACOTE=fotos
PADRAO_PACOTE='fotos-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*.tar.age'
PASTAS_ORIGINAIS=(library upload profile)
DIAS_REMOVIDAS=30
IDADE_MAX_DUMP_H=26

DESTINO=""
RETENCAO=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destino) DESTINO="${2:-}"; shift 2 || falha "--destino precisa de uma pasta." ;;
    --retencao) RETENCAO=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) falha "opção desconhecida: $1 (veja --help)" ;;
  esac
done

descobrir_home
conferir_env
command -v age >/dev/null 2>&1 || falha "sem o age no host (sudo apt install age)."
DESTINATARIO="$(valor_env AGE_DESTINATARIO)"
case "$DESTINATARIO" in
  age1*) ;;
  *) falha "AGE_DESTINATARIO vazio ou inválido no .env (precisa ser a chave pública age1...)." ;;
esac
[ -n "$DESTINO" ] || DESTINO="$(valor_env BACKUP_DESTINO)"
[ -n "$DESTINO" ] || DESTINO="$HOME_DIR/backups"
DESTINO="$(absoluto "$DESTINO")"
BIBLIOTECA="$HOME_DIR/data/biblioteca"
umask 077
mkdir -p "$DESTINO/arquivos" "$DESTINO/removidas" || falha "não consegui criar as pastas em $DESTINO."
conferir_instancia_da_pasta "$DESTINO" "$(valor_env COMPOSE_PROJECT_NAME)" "$RETENCAO"
[ -d "$BIBLIOTECA" ] || falha "sem $BIBLIOTECA: o Immich já subiu alguma vez?"

TMP="$DESTINO/.tmp-exportar-$$"
rm -rf "$DESTINO"/.tmp-exportar-* 2>/dev/null || true
limpar() {
  local codigo=$?
  rm -rf "$TMP"
  exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT TERM
mkdir -p "$TMP" || falha "não consegui criar $TMP."

# --- 1. Originais, incremental ---------------------------------------------------------------------------------
novos=0; ja=0; bytes_novos=0
: >"$TMP/indice.tsv"
for pasta in "${PASTAS_ORIGINAIS[@]}"; do
  [ -d "$BIBLIOTECA/$pasta" ] || continue
  while IFS= read -r -d '' arq; do
    rel="${arq#"$BIBLIOTECA"/}"
    [ -r "$arq" ] || falha "sem leitura em $arq (dono do arquivo: $(stat -c %U "$arq" 2>/dev/null || echo ?))."
    tam="$(wc -c <"$arq" | tr -d ' ')"
    printf '%s\t%s\n' "$rel" "$tam" >>"$TMP/indice.tsv"
    alvo="$DESTINO/arquivos/$rel.age"
    if [ -s "$alvo" ]; then ja=$((ja + 1)); continue; fi
    mkdir -p "$(dirname "$alvo")" || falha "não consegui criar $(dirname "$alvo")."
    age -r "$DESTINATARIO" -o "$alvo.parcial" "$arq" || { rm -f "$alvo.parcial"; falha "age falhou em $rel."; }
    mv "$alvo.parcial" "$alvo" || falha "não consegui renomear $alvo.parcial."
    novos=$((novos + 1)); bytes_novos=$((bytes_novos + tam))
  # -mmin +10: um envio em andamento não entra pela metade (o original nunca muda depois de gravado).
  done < <(find "$BIBLIOTECA/$pasta" -type f ! -name '.immich' -mmin +10 -print0)
done
total="$(wc -l <"$TMP/indice.tsv" | tr -d ' ')"
log "originais: $total na biblioteca, $novos cifrados agora ($bytes_novos bytes), $ja já estavam no backup"

# --- 2. O que sumiu da biblioteca vai para removidas/ -------------------------------------------------------------
hoje="$(date +%Y-%m-%d)"
removidos=0
cut -f1 "$TMP/indice.tsv" | sed 's/$/.age/' | LC_ALL=C sort >"$TMP/esperados"
(cd "$DESTINO/arquivos" && find . -type f -name '*.age' | sed 's|^\./||' | LC_ALL=C sort) >"$TMP/no-backup"
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  mkdir -p "$DESTINO/removidas/$hoje/$(dirname "$rel")"
  mv "$DESTINO/arquivos/$rel" "$DESTINO/removidas/$hoje/$rel" || falha "não consegui mover $rel para removidas."
  removidos=$((removidos + 1))
done < <(LC_ALL=C comm -13 "$TMP/esperados" "$TMP/no-backup")
find "$DESTINO/arquivos" -name '*.parcial' -delete 2>/dev/null || true
find "$DESTINO/arquivos" -mindepth 1 -type d -empty -delete 2>/dev/null || true
[ "$removidos" -eq 0 ] || log "$removidos arquivos saíram da biblioteca: guardados em removidas/$hoje por $DIAS_REMOVIDAS dias"
while IFS= read -r velha; do
  rm -rf -- "$velha" && log "apagada pelo prazo de $DIAS_REMOVIDAS dias: removidas/$(basename "$velha")"
done < <(find "$DESTINO/removidas" -mindepth 1 -maxdepth 1 -type d -name '????-??-??' -mtime +"$DIAS_REMOVIDAS")

rm -f "$TMP/esperados" "$TMP/no-backup"

# --- 3. Pacote do banco -------------------------------------------------------------------------------------------
DUMP="$(ls -1t "$BIBLIOTECA"/backups/immich-db-backup-*.sql.gz 2>/dev/null | head -n 1)"
[ -n "$DUMP" ] || falha "sem dump do banco em $BIBLIOTECA/backups (o Immich faz às 02:00; veja \"backup.database\" no immich-config.json)."
idade_h=$(( ( $(date +%s) - $(stat -c %Y "$DUMP" 2>/dev/null || stat -f %m "$DUMP") ) / 3600 ))
[ "$idade_h" -le "$IDADE_MAX_DUMP_H" ] || falha "o dump mais novo ($(basename "$DUMP")) tem ${idade_h} h: o backup do banco do Immich parou?"
gzip -t "$DUMP" || falha "o dump $(basename "$DUMP") está corrompido."
cp "$DUMP" "$TMP/" || falha "não consegui copiar o dump."
cp "$ENV_FILE" "$TMP/env" || falha "não consegui copiar o .env."

IMAGEM="$(grep -E '^[[:space:]]*image:[[:space:]]*ghcr.io/immich-app/immich-server' "$FOTOS_APP/docker-compose.yml" | head -n 1 | awk '{print $2}')"
COMMIT="$(git -C "$(caminho_docker "$APP")" rev-parse HEAD 2>/dev/null || echo desconhecido)"
[ -z "$(git -C "$(caminho_docker "$APP")" status --porcelain 2>/dev/null)" ] || COMMIT="$COMMIT+alterado"
CARIMBO="$(date +%Y%m%d-%H%M)"
NOME="fotos-$CARIMBO.tar.age"
[ ! -e "$DESTINO/$NOME" ] || { CARIMBO="$(date +%Y%m%d-%H%M%S)"; NOME="fotos-$CARIMBO.tar.age"; }
json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
{
  printf '{\n  "formato": 1,\n'
  printf '  "criado_em": "%s",\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf '  "maquina": "%s",\n' "$(json "$(hostname 2>/dev/null || echo desconhecida)")"
  printf '  "commit": "%s",\n' "$(json "$COMMIT")"
  printf '  "imagem": "%s",\n' "$(json "${IMAGEM:-desconhecida}")"
  printf '  "dump": "%s",\n' "$(json "$(basename "$DUMP")")"
  printf '  "originais": %s\n}\n' "$total"
} >"$TMP/manifesto.json"
SOMAS="$(cd "$TMP" && for f in *; do printf '%s  %s\n' "$(sha256_de "$f")" "$f"; done)" || falha "não consegui calcular os hashes."
printf '%s\n' "$SOMAS" >"$TMP/SHA256SUMS" || falha "não consegui gravar SHA256SUMS."
PARCIAL="$DESTINO/$NOME.parcial"
tar -C "$TMP" -cf - . | age -r "$DESTINATARIO" >"$PARCIAL" || { rm -f "$PARCIAL"; falha "tar ou age falhou."; }
[ -s "$PARCIAL" ] || { rm -f "$PARCIAL"; falha "o pacote saiu vazio."; }
mv "$PARCIAL" "$DESTINO/$NOME" || falha "não consegui renomear o pacote."
printf '%s  %s\n' "$(sha256_de "$DESTINO/$NOME")" "$NOME" >"$DESTINO/$NOME.sha256"
log "feito: $DESTINO/$NOME (dump $(basename "$DUMP"), $total originais)"

if [ "$RETENCAO" -eq 1 ]; then
  while IFS= read -r velho; do
    [ -n "$velho" ] || continue
    rm -f -- "$DESTINO/$velho" "$DESTINO/$velho.sha256" && log "apagado pela retenção (7 diários, 4 semanais): $velho"
  done < <(pacotes_a_apagar "$DESTINO" 7 4)
fi
exit 0
