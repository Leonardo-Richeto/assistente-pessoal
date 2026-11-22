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
#   ... --primeira-vez                                          # só na 1ª rodada: marca a pasta (.instancia)
#
# Sem a marca .instancia, o backup recusa a pasta: com o HD desmontado, ele gravaria no SSD.
# Precisa do age no host (o preparar_host.sh instala): um "docker run" por arquivo seria lento demais.
source "$(dirname "$0")/comum.sh"

PREFIXO_PACOTE=fotos
PADRAO_PACOTE='fotos-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*.tar.age'
PASTAS_ORIGINAIS=(library upload profile)
DIAS_REMOVIDAS=30
# O dump do Immich é das 02:00 e o backup roda às 04:05: o de ontem (26 h) já é velho.
IDADE_MAX_DUMP_MIN=$((23 * 60))
# Mais que isto saindo da biblioteca num dia só para o backup (disco com erro, pasta sem leitura, caminho mudado);
# remoção grande de verdade: rode com FOTOS_ACEITAR_REMOCOES=1.
LIMITE_REMOCOES=50

DESTINO=""
RETENCAO=0
PRIMEIRA=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destino) DESTINO="${2:-}"; shift 2 || falha "--destino precisa de uma pasta." ;;
    --retencao) RETENCAO=1; shift ;;
    --primeira-vez) PRIMEIRA=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
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
if [ ! -f "$DESTINO/.instancia" ]; then
  [ "$PRIMEIRA" -eq 1 ] || falha "sem $DESTINO/.instancia: o HD do backup está montado? Na 1ª rodada, use --primeira-vez."
  mkdir -p "$DESTINO" || falha "não consegui criar $DESTINO."
fi
conferir_instancia_da_pasta "$DESTINO" "$(valor_env COMPOSE_PROJECT_NAME)" 1
mkdir -p "$DESTINO/arquivos" "$DESTINO/removidas" || falha "não consegui criar as pastas em $DESTINO."
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
# Índice da rodada anterior (caminho, bytes, mtime): arquivo que mudou é cifrado de novo (o .age velho vai para
# removidas/). Fica fora do pacote cifrado só com o que os nomes em arquivos/ já mostram.
ANTERIOR="$DESTINO/indice.tsv"
[ -f "$ANTERIOR" ] || : >"$ANTERIOR"
hoje="$(date +%Y-%m-%d)"
guardar_removido() {  # <rel.age>
  mkdir -p "$DESTINO/removidas/$hoje/$(dirname "$1")" || falha "não consegui criar removidas/$hoje."
  mv "$DESTINO/arquivos/$1" "$DESTINO/removidas/$hoje/$1" || falha "não consegui mover $1 para removidas."
}
for pasta in "${PASTAS_ORIGINAIS[@]}"; do
  [ -d "$BIBLIOTECA/$pasta" ] || falha "sem $BIBLIOTECA/$pasta: a biblioteca mudou de lugar? Nada foi tirado do backup."
  # Lista "caminho<TAB>bytes<TAB>mtime"; qualquer erro de leitura (pasta sem permissão, disco) para o backup, e
  # nome com TAB ou quebra de linha também (quebraria o índice).
  python3 -I - "$BIBLIOTECA/$pasta" >"$TMP/achados-$pasta" <<'PY' \
    || falha "não consegui listar $BIBLIOTECA/$pasta (veja acima). Nada foi tirado do backup."
import os, sys
raiz = sys.argv[1]
def erro(e):
    raise e
for d, _, arquivos in os.walk(raiz, onerror=erro):
    for nome in arquivos:
        if nome == ".immich":
            continue
        caminho = os.path.join(d, nome)
        rel = os.path.relpath(caminho, raiz)
        if "\t" in rel or "\n" in rel:
            sys.exit(f"nome com TAB ou quebra de linha: {rel!r}")
        st = os.stat(caminho)
        print(f"{rel}\t{st.st_size}\t{int(st.st_mtime)}")
PY
  sed "s|^|$pasta/|" "$TMP/achados-$pasta" >>"$TMP/indice.tsv"
done
[ -f "$TMP/indice.tsv" ] || : >"$TMP/indice.tsv"
# Uma passada só pelo índice anterior: 4ª coluna "mudou" quando bytes ou mtime diferem da rodada anterior.
# FILENAME, não NR == FNR: com o índice anterior vazio (1ª rodada), NR == FNR valeria para o atual também.
awk -F'\t' -v OFS='\t' -v anterior="$ANTERIOR" 'FILENAME == anterior { antes[$1] = $2 OFS $3; next }
  { print $1, $2, $3, (($1 in antes) && antes[$1] != $2 OFS $3) ? "mudou" : "-" }' "$ANTERIOR" "$TMP/indice.tsv" \
  >"$TMP/plano.tsv" || falha "não consegui comparar com o índice anterior."
novos=0; refeitos=0; ja=0; recentes=0; bytes_novos=0
agora="$(date +%s)"
while IFS="$(printf '\t')" read -r rel tam mtime estado; do
  arq="$BIBLIOTECA/$rel"
  [ -r "$arq" ] || falha "sem leitura em $arq (dono: $(stat -c %U "$arq" 2>/dev/null || echo ?)). Nada foi tirado do backup."
  alvo="$DESTINO/arquivos/$rel.age"
  if [ -s "$alvo" ]; then
    [ "$estado" = mudou ] || { ja=$((ja + 1)); continue; }
    guardar_removido "$rel.age"; refeitos=$((refeitos + 1))
  fi
  # Gravado há menos de 10 min: pode ser um envio pela metade. Fica no índice (não é removido) e entra amanhã.
  if [ $(( agora - mtime )) -lt 600 ]; then recentes=$((recentes + 1)); continue; fi
  mkdir -p "$(dirname "$alvo")" || falha "não consegui criar $(dirname "$alvo")."
  age -r "$DESTINATARIO" -o "$alvo.parcial" "$arq" || { rm -f "$alvo.parcial"; falha "age falhou em $rel."; }
  [ -s "$alvo.parcial" ] || { rm -f "$alvo.parcial"; falha "o .age de $rel saiu vazio."; }
  mv "$alvo.parcial" "$alvo" || falha "não consegui renomear $alvo.parcial."
  novos=$((novos + 1)); bytes_novos=$((bytes_novos + tam))
done <"$TMP/plano.tsv"
total="$(wc -l <"$TMP/indice.tsv" | tr -d ' ')"
log "originais: $total na biblioteca, $novos cifrados agora ($bytes_novos bytes), $refeitos refeitos (mudaram), $ja já estavam, $recentes recentes (entram amanhã)"

# --- 2. O que sumiu da biblioteca vai para removidas/ -------------------------------------------------------------
cut -f1 "$TMP/indice.tsv" | sed 's/$/.age/' | LC_ALL=C sort >"$TMP/esperados"
(cd "$DESTINO/arquivos" && find . -type f -name '*.age' | sed 's|^\./||' | LC_ALL=C sort) >"$TMP/no-backup" \
  || falha "não consegui listar $DESTINO/arquivos."
LC_ALL=C comm -13 "$TMP/esperados" "$TMP/no-backup" >"$TMP/sumiram"
removidos="$(wc -l <"$TMP/sumiram" | tr -d ' ')"
if [ "$removidos" -gt "$LIMITE_REMOCOES" ] && [ "${FOTOS_ACEITAR_REMOCOES:-0}" != 1 ]; then
  falha "$removidos originais sumiram da biblioteca desde o último backup (limite $LIMITE_REMOCOES). Nada foi tirado do backup. Se a remoção foi de propósito, rode com FOTOS_ACEITAR_REMOCOES=1."
fi
while IFS= read -r rel; do
  [ -n "$rel" ] && guardar_removido "$rel"
done <"$TMP/sumiram"
find "$DESTINO/arquivos" -name '*.parcial' -delete 2>/dev/null || true
find "$DESTINO/arquivos" -mindepth 1 -type d -empty -delete 2>/dev/null || true
[ "$removidos" -eq 0 ] || log "$removidos arquivos saíram da biblioteca: guardados em removidas/$hoje por $DIAS_REMOVIDAS dias"
while IFS= read -r velha; do
  rm -rf -- "$velha" && log "apagada pelo prazo de $DIAS_REMOVIDAS dias: removidas/$(basename "$velha")"
done < <(find "$DESTINO/removidas" -mindepth 1 -maxdepth 1 -type d -name '????-??-??' -mtime +"$DIAS_REMOVIDAS")
cp "$TMP/indice.tsv" "$ANTERIOR.novo" && mv "$ANTERIOR.novo" "$ANTERIOR" || falha "não consegui gravar $ANTERIOR."
# O índice do pacote leva só o que já tem .age (os recentes entram amanhã): é ele que o ensaio confere.
while IFS="$(printf '\t')" read -r rel tam _; do
  [ -s "$DESTINO/arquivos/$rel.age" ] && printf '%s\t%s\n' "$rel" "$tam"
done <"$TMP/indice.tsv" >"$TMP/indice-pacote.tsv"
mv "$TMP/indice-pacote.tsv" "$TMP/indice.tsv" || falha "não consegui montar o índice do pacote."

rm -f "$TMP/esperados" "$TMP/no-backup" "$TMP/sumiram" "$TMP/plano.tsv" "$TMP"/achados-*

# --- 3. Pacote do banco -------------------------------------------------------------------------------------------
DUMP="$(ls -1t "$BIBLIOTECA"/backups/immich-db-backup-*.sql.gz 2>/dev/null | head -n 1)"
[ -n "$DUMP" ] || falha "sem dump do banco em $BIBLIOTECA/backups (o Immich faz às 02:00; veja \"backup.database\" no immich-config.json)."
idade_min=$(( ( $(date +%s) - $(stat -c %Y "$DUMP" 2>/dev/null || stat -f %m "$DUMP") ) / 60 ))
[ "$idade_min" -le "$IDADE_MAX_DUMP_MIN" ] || falha "o dump mais novo ($(basename "$DUMP")) tem $((idade_min / 60)) h: o backup do banco do Immich das 02:00 parou?"
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
