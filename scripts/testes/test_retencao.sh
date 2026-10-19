#!/usr/bin/env bash
# Teste da retenção do exportar.sh (7 diários, 4 semanais), sem Docker.
#   bash scripts/testes/test_retencao.sh
source "$(dirname "$0")/../lib.sh"

PASTA="$(mktemp -d)"
trap 'rm -rf "$PASTA"' EXIT
falhas=0
confere() {  # <descrição> <esperado> <obtido>
  if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FALHA $1"; echo "  esperado: $2"; echo "  obtido:   $3"; falhas=$((falhas + 1)); fi
}

# 40 dias de pacotes, dois por dia nos 3 dias mais novos; mais um arquivo de outro nome.
for i in $(seq 0 39); do
  dia="$(date -d "2026-10-19 -$i day" +%Y%m%d 2>/dev/null || date -j -v-"${i}"d -f %Y%m%d 20261019 +%Y%m%d)"
  touch "$PASTA/assistente-$dia-0315.tar.age"
  [ "$i" -lt 3 ] && touch "$PASTA/assistente-$dia-1200.tar.age"
done
touch "$PASTA/assistente-manual.tar.age" "$PASTA/outra-coisa.tar.age"

apagar="$(pacotes_a_apagar "$PASTA" 7 4 | sort)"
ficam="$(cd "$PASTA" && ls -1 $PADRAO_PACOTE | sort | comm -23 - <(printf '%s\n' "$apagar"))"

# Dias: 19/10 (12:00) ... 13/10. Semanas ISO (o mais novo de cada uma, como o restic): 43 e 42
# já caem nos diários (19/10 e 18/10); sobram a 41 (domingo 11/10) e a 40 (domingo 04/10).
esperado="$(printf '%s\n' \
  assistente-20261004-0315.tar.age assistente-20261011-0315.tar.age \
  assistente-20261013-0315.tar.age assistente-20261014-0315.tar.age assistente-20261015-0315.tar.age \
  assistente-20261016-0315.tar.age assistente-20261017-1200.tar.age assistente-20261018-1200.tar.age \
  assistente-20261019-1200.tar.age | sort)"
confere "ficam 7 diários (o mais novo de cada dia) e as 4 semanas" "$esperado" "$ficam"
confere "nome fora do padrão não entra na lista" "" "$(printf '%s\n' "$apagar" | grep -v '^assistente-2026' || true)"
confere "total apagado" "34" "$(printf '%s\n' "$apagar" | grep -c .)"

[ "$falhas" -eq 0 ] && echo "test_retencao: ok" || { echo "test_retencao: $falhas falha(s)"; exit 1; }
