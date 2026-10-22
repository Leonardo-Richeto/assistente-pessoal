#!/usr/bin/env bash
# Teste da lista de notas desatualizadas: o marcas-desatualizadas.sh com um `docker` FALSO no PATH, e o
# lint-diario.sh (com um lint falso) juntando o marcas.md ao relatório, sem chamar docker.
# Sem vault real, sem banco, sem container.
#   bash scripts/testes/test_lint_desatualizadas.sh
set -u

DEPLOY="$(cd "$(dirname "$0")/../.." && pwd)/deploy/vault"
MARCAS_SH="$DEPLOY/marcas-desatualizadas.sh"
LINT_SH="$DEPLOY/lint-diario.sh"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
falhas=0
LINHA="- 60-planos/carro.md — O plano fala do carro vendido em 2025 (marca 3, 2026-10-21)"
AVISO_ERRO="AVISO: não consegui consultar as marcas (2)."

# Vault com o lint falso (3ª linha é o resumo).
mkdir -p "$RAIZ/vault/90-meta"
printf '%s\n' 'import sys' 'print("Lint falso")' 'print("Notas: 1")' 'print("Resumo: 0 ERRO")' 'sys.exit(0)' \
  > "$RAIZ/vault/90-meta/lint-do-vault.py"

# `docker` falso: guarda os argumentos e responde conforme DOCKER_FALSO (linha | vazio | erro).
mkdir -p "$RAIZ/bin"
cat > "$RAIZ/bin/docker" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$RAIZ/docker-args"
case "\${DOCKER_FALSO:-}" in
  linha) echo "$LINHA" ;;
  vazio) ;;
  *) echo "erro falso do banco" >&2; exit 2 ;;
esac
EOF
chmod +x "$RAIZ/bin/docker"

# Roda o marcas-desatualizadas.sh com o docker falso; imprime o código de saída.
marcas() {  # <pasta> <DOCKER_FALSO>
  PATH="$RAIZ/bin:$PATH" DOCKER_FALSO="$2" ASSISTENTE_DIR=/srv/assistente/app LINT_DIR="$RAIZ/$1" \
    bash "$MARCAS_SH" >/dev/null 2>&1
  echo $?
}

# Roda o lint-diario.sh (docker falso no PATH, para ver se ele é chamado); imprime o código de saída.
lint() {  # <pasta>
  PATH="$RAIZ/bin:$PATH" DOCKER_FALSO=linha VAULT_PATH="$RAIZ/vault" LINT_DIR="$RAIZ/$1" \
    bash "$LINT_SH" >/dev/null 2>&1
  echo $?
}

falhou() { echo "FALHOU: $*"; falhas=$((falhas + 1)); }
sobras() { find "$RAIZ/$1" -name '*.parcial*' | grep -c .; }

# ---------------- marcas-desatualizadas.sh ----------------

# (a) com marca: marcas.md com a linha, código 0, comando certo, sem sobra.
codigo="$(marcas m-linha linha)"
arq="$RAIZ/m-linha/marcas.md"
if [ "$codigo" -ne 0 ]; then falhou "marcas com linha, código $codigo (esperado 0)"
elif [ "$(cat "$arq")" != "$LINHA" ]; then falhou "marcas com linha, conteúdo: $(cat "$arq")"
elif ! grep -qxF "compose --project-directory /srv/assistente/app exec -T servidor python -m assistente.desatualizadas" \
       "$RAIZ/docker-args"; then falhou "comando do docker diferente: $(cat "$RAIZ/docker-args")"
elif [ "$(sobras m-linha)" -ne 0 ]; then falhou "marcas com linha, sobrou .parcial"
elif [ "$(stat -f %Lp "$arq" 2>/dev/null || stat -c %a "$arq")" != "644" ]; then falhou "marcas.md sem modo 644"
else echo "ok marcas com linha: arquivo com a linha, código 0, modo 644"
fi

# (b) sem marca: marcas.md vazio, código 0.
codigo="$(marcas m-vazio vazio)"
arq="$RAIZ/m-vazio/marcas.md"
if [ "$codigo" -eq 0 ] && [ -f "$arq" ] && [ ! -s "$arq" ] && [ "$(sobras m-vazio)" -eq 0 ]; then
  echo "ok marcas sem marca: arquivo vazio, código 0"
else falhou "marcas sem marca, código $codigo ou arquivo ausente/não vazio"
fi

# (c) docker falha: a linha de AVISO com o código no lugar da lista anterior, e o código da consulta.
mkdir -p "$RAIZ/m-erro" && echo "$LINHA" > "$RAIZ/m-erro/marcas.md"
codigo="$(marcas m-erro erro)"
arq="$RAIZ/m-erro/marcas.md"
if [ "$codigo" -ne 2 ]; then falhou "marcas com erro, código $codigo (esperado 2)"
elif [ "$(cat "$arq")" != "$AVISO_ERRO" ]; then falhou "marcas com erro, conteúdo: $(cat "$arq")"
elif [ "$(sobras m-erro)" -ne 0 ]; then falhou "marcas com erro, sobrou .parcial"
else echo "ok marcas com erro: só a linha de AVISO e código 2"
fi

# (d) link deixado no lugar do .parcial antigo não é seguido (o nome do temporário é novo).
mkdir -p "$RAIZ/m-link" && echo "alvo intacto" > "$RAIZ/alvo"
ln -s "$RAIZ/alvo" "$RAIZ/m-link/marcas.md.parcial"
codigo="$(marcas m-link linha)"
if [ "$codigo" -eq 0 ] && [ "$(cat "$RAIZ/alvo")" = "alvo intacto" ] && [ "$(cat "$RAIZ/m-link/marcas.md")" = "$LINHA" ]; then
  echo "ok marcas com link plantado: o alvo do link ficou intacto"
else falhou "marcas com link plantado, código $codigo ou alvo mudou: $(cat "$RAIZ/alvo")"
fi

# ---------------- lint-diario.sh juntando marcas.md ----------------

rm -f "$RAIZ/docker-args"

# (e) marcas.md novo com linha: seção, a linha e código 0.
mkdir -p "$RAIZ/l-linha" && echo "$LINHA" > "$RAIZ/l-linha/marcas.md"
codigo="$(lint l-linha)"
rel="$RAIZ/l-linha/ultimo.md"
if [ "$codigo" -ne 0 ]; then falhou "lint com marca, código $codigo (esperado 0)"
elif ! grep -qx "## Notas marcadas como desatualizadas" "$rel"; then falhou "lint com marca, seção ausente"
elif ! grep -qxF -- "$LINHA" "$rel"; then falhou "lint com marca, linha da marca ausente"
else echo "ok lint com marca: seção, linha e código 0"
fi

# (f) marcas.md vazio: relatório sem seção nem aviso.
mkdir -p "$RAIZ/l-vazio" && : > "$RAIZ/l-vazio/marcas.md"
codigo="$(lint l-vazio)"
if [ "$codigo" -eq 0 ] && ! grep -q "desatualizadas\|marcas" "$RAIZ/l-vazio/ultimo.md"; then
  echo "ok lint sem marca: relatório sem seção"
else falhou "lint sem marca, código $codigo ou seção/aviso presente"
fi

# (g) marcas.md com o AVISO da consulta: a linha de AVISO, sem seção, código do lint mantido.
mkdir -p "$RAIZ/l-erro" && echo "$AVISO_ERRO" > "$RAIZ/l-erro/marcas.md"
codigo="$(lint l-erro)"
rel="$RAIZ/l-erro/ultimo.md"
if [ "$codigo" -ne 0 ]; then falhou "lint com aviso, código $codigo (esperado 0)"
elif ! grep -qxF "$AVISO_ERRO" "$rel"; then falhou "lint com aviso, linha ausente"
elif grep -q "## Notas marcadas" "$rel"; then falhou "lint com aviso, seção presente"
else echo "ok lint com aviso da consulta: a linha, sem seção, código 0"
fi

# (h) marcas.md com mais de 24 h: só o AVISO de lista velha, sem a lista.
mkdir -p "$RAIZ/l-velho" && echo "$LINHA" > "$RAIZ/l-velho/marcas.md"
touch -t 202001010000 "$RAIZ/l-velho/marcas.md"
codigo="$(lint l-velho)"
rel="$RAIZ/l-velho/ultimo.md"
if [ "$codigo" -ne 0 ]; then falhou "lint com lista velha, código $codigo (esperado 0)"
elif ! grep -qxF "AVISO: lista de marcas com mais de 24 h." "$rel"; then falhou "lint com lista velha, aviso ausente"
elif grep -qF -- "$LINHA" "$rel" || grep -q "## Notas marcadas" "$rel"; then falhou "lint com lista velha, lista presente"
else echo "ok lint com lista velha: só o aviso de mais de 24 h"
fi

# (i) sem marcas.md: pula em silêncio.
mkdir -p "$RAIZ/l-sem"
codigo="$(lint l-sem)"
if [ "$codigo" -eq 0 ] && ! grep -q "marcas\|desatualizadas" "$RAIZ/l-sem/ultimo.md"; then
  echo "ok lint sem marcas.md: pulou em silêncio"
else falhou "lint sem marcas.md, código $codigo ou aviso presente"
fi

# (j) o lint nunca chamou o docker.
if [ -e "$RAIZ/docker-args" ]; then falhou "o lint chamou o docker: $(cat "$RAIZ/docker-args")"
else echo "ok lint não chama docker"
fi

# (k) ponta a ponta: marcas às 03:35 e lint às 03:40 na mesma pasta.
codigo_m="$(marcas l-junto linha)"
codigo="$(lint l-junto)"
if [ "$codigo_m" -eq 0 ] && [ "$codigo" -eq 0 ] && grep -qxF -- "$LINHA" "$RAIZ/l-junto/ultimo.md"; then
  echo "ok ponta a ponta: a linha gravada pelas marcas aparece no relatório"
else falhou "ponta a ponta, códigos $codigo_m/$codigo ou linha ausente"
fi

[ "$falhas" -eq 0 ] && echo "test_lint_desatualizadas: ok" || { echo "test_lint_desatualizadas: $falhas falha(s)"; exit 1; }
