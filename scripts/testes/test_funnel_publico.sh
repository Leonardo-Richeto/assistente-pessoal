#!/usr/bin/env bash
# Teste do Funnel pela internet (conferir_funnel_publico do lib.sh), sem rede: um curl falso no PATH
# responde o DoH e o pedido ao /mcp conforme as variáveis FALSO_*.
#   bash scripts/testes/test_funnel_publico.sh
source "$(dirname "$0")/../lib.sh"

PASTA="$(mktemp -d)"
trap 'rm -rf "$PASTA"' EXIT
falhas=0
confere() {  # <descrição> <esperado> <obtido>
  if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FALHA $1"; echo "  esperado: $2"; echo "  obtido:   $3"; falhas=$((falhas + 1)); fi
}

# FALSO_DOH_1 e FALSO_DOH_2: resposta de cada DoH ("falha" = curl sem conexão).
# FALSO_HTTP: código do /mcp. Cada chamada fica anotada em $PASTA/chamadas.
cat >"$PASTA/curl" <<'FALSO'
#!/usr/bin/env bash
echo "$*" >>"$FALSO_PASTA/chamadas"
case "$*" in
  *doh1.teste*) r="$FALSO_DOH_1" ;;
  *doh2.teste*) r="$FALSO_DOH_2" ;;
  *) printf '%s' "$FALSO_HTTP"; exit 0 ;;
esac
[ "$r" = falha ] && exit 7
printf '%s\n' "$r"
FALSO
chmod +x "$PASTA/curl"
export PATH="$PASTA:$PATH" FALSO_PASTA="$PASTA"
DOH_URLS="https://doh1.teste/dns-query https://doh2.teste/resolve"
URL="https://assistente.exemplo.ts.net"

COM_IP='{"Status":0,"Answer":[{"name":"assistente.exemplo.ts.net","type":1,"TTL":60,"data":"203.0.113.7"}]}'
SEM_NOME='{"Status":3,"Authority":[{"name":"ts.net","type":6,"data":"ns.ts.net. 1 2 3 4 5"}]}'

rodar() {  # <doh1> <doh2> <http> -> "<código>|<linha>"
  : >"$PASTA/chamadas"
  local linha rc
  linha="$(FALSO_DOH_1="$1" FALSO_DOH_2="$2" FALSO_HTTP="$3" conferir_funnel_publico "$URL")"; rc=$?
  printf '%s|%s' "$rc" "$linha"
}

saida="$(rodar "$COM_IP" falha 401)"
confere "DNS público com IP e 401: passa" "0" "${saida%%|*}"
confere "o curl do /mcp vai ao IP público (--resolve)" "1" "$(grep -c -- '--resolve assistente.exemplo.ts.net:443:203.0.113.7' "$PASTA/chamadas")"

saida="$(rodar "$SEM_NOME" "$SEM_NOME" 401)"
confere "nome fora do DNS público: falha, mesmo com o servidor de pé" "1" "${saida%%|*}"
confere "a linha diz que o nome não existe" "1" "$(printf '%s' "$saida" | grep -c 'não existe no DNS público')"
confere "sem IP, o /mcp nem é chamado" "0" "$(grep -c -- '--resolve' "$PASTA/chamadas")"

saida="$(rodar falha "$COM_IP" 401)"
confere "primeiro DoH fora do ar: usa o segundo" "0" "${saida%%|*}"

saida="$(rodar falha falha 401)"
confere "nenhum DoH responde: falha" "1" "${saida%%|*}"
confere "a linha diz que nenhum DNS respondeu" "1" "$(printf '%s' "$saida" | grep -c 'nenhum DNS público respondeu')"

saida="$(rodar "$COM_IP" falha 502)"
confere "Funnel sem o servidor (502): falha" "1" "${saida%%|*}"
confere "a linha mostra o código" "1" "$(printf '%s' "$saida" | grep -c '= 502 (esperado 401)')"

saida="$(rodar '<html>bloqueado</html>' "$COM_IP" 401)"
confere "resposta que não é DNS: tenta o próximo" "0" "${saida%%|*}"

[ "$falhas" -eq 0 ] && echo "test_funnel_publico: ok" || { echo "test_funnel_publico: $falhas falha(s)"; exit 1; }
