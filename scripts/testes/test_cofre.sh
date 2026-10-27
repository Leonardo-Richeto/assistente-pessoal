#!/usr/bin/env bash
# Teste do cofre (Ficha 11) com dados SINTÉTICOS, numa pasta descartável. Precisa de Docker e de python3.
#   bash scripts/testes/test_cofre.sh <pasta-vazia-de-teste>
#
# Sobe o cofre num projeto ensaio-cofre-*, sem Tailscale, e confere: cadastro fechado recusa conta; com o
# cadastro aberto, uma conta de teste entra pela API; fechado de novo, a conferência passa; o painel /admin
# não existe; o backup sai cifrado e o ensaio de restauração devolve as mesmas contagens (1 conta).
# No fim, derruba o projeto e apaga a pasta.
source "$(dirname "$0")/../../cofre/scripts/comum.sh"

[ "$#" -eq 1 ] || { sed -n '2,8p' "$0"; exit 2; }
BASE="$(absoluto "$1")"
pasta_vazia "$BASE" || falha "$BASE precisa estar vazia ou não existir."
mkdir -p "$BASE/cofre" "$BASE/chave" || falha "não consegui criar $BASE."
PROJETO="ensaio-cofre-teste-$$"
PORTA=$((18100 + $$ % 300))

limpar() {
  local codigo=$?
  if [ -f "$BASE/cofre/.env" ] && [ "$(valor_env COMPOSE_PROJECT_NAME "$BASE/cofre/.env")" = "$PROJETO" ]; then
    COFRE_HOME="$BASE/cofre" descobrir_home
    dc down -v --remove-orphans >/dev/null 2>&1
  fi
  rm -rf "$BASE"
  [ "$codigo" -eq 0 ] && echo "test_cofre: ok" || echo "test_cofre: FALHOU" >&2
  exit "$codigo"
}
trap limpar EXIT

log "chave age de teste"
garantir_imagem_ferramentas
docker run --rm "$IMAGEM_FERRAMENTAS" age-keygen 2>/dev/null >"$BASE/chave/identidade.txt" || falha "age-keygen falhou."
PUBLICA="$(grep -o 'age1[0-9a-z]*' "$BASE/chave/identidade.txt" | head -n 1)"
[ -n "$PUBLICA" ] || falha "não achei a chave pública."

sed -e "s#^COFRE_HOME=.*#COFRE_HOME=$(caminho_docker "$BASE/cofre")#" \
    -e "s#^COMPOSE_PROJECT_NAME=.*#COMPOSE_PROJECT_NAME=$PROJETO#" \
    -e "s#^PORTA_HOST=.*#PORTA_HOST=$PORTA#" \
    -e "s#^COFRE_UID=.*#COFRE_UID=$(id -u)#" -e "s#^COFRE_GID=.*#COFRE_GID=$(id -g)#" \
    -e "s#^COMPOSE_PROFILES=.*#COMPOSE_PROFILES=#" \
    -e "s#^DOMINIO=.*#DOMINIO=http://127.0.0.1:$PORTA#" \
    -e "s#^AGE_DESTINATARIO=.*#AGE_DESTINATARIO=$PUBLICA#" "$APP/cofre/.env.example" >"$BASE/cofre/.env"
export COFRE_HOME="$BASE/cofre"
descobrir_home

log "1. preparar (cadastro fechado)"
bash "$APP/cofre/scripts/preparar.sh" || falha "preparar.sh falhou."

# Cadastro pela API, como o app faria no Vaultwarden 1.37 (dois passos: o token de verificação volta direto, sem
# e-mail; depois o register/finish). Os campos cifrados são sintéticos: o servidor não os abre.
registrar() {  # -> código HTTP do último passo
  local base="http://127.0.0.1:$PORTA/identity/accounts/register" token
  token="$(curl -s -m 10 -H 'Content-Type: application/json' -X POST "$base/send-verification-email" \
    -d '{"email": "teste@exemplo.invalid", "name": "Teste", "receiveMarketingEmails": false}')"
  token="${token//\"/}"
  [[ "$token" =~ ^[A-Za-z0-9._-]+$ ]] || { echo recusado; return 0; }
  curl -s -m 10 -o "$BASE/registro.json" -w '%{http_code}' -H 'Content-Type: application/json' -X POST "$base/finish" --data @- <<JSON
{"email": "teste@exemplo.invalid", "emailVerificationToken": "$token", "masterPasswordHash": "aGFzaC1zaW50ZXRpY28=",
 "masterPasswordHint": null, "userSymmetricKey": "2.c2ludGV0aWNv|c2ludGV0aWNv|c2ludGV0aWNv", "kdf": 0, "kdfIterations": 600000,
 "userAsymmetricKeys": {"publicKey": "c2ludGV0aWNh", "encryptedPrivateKey": "2.c2ludGV0aWNv|c2ludGV0aWNv|c2ludGV0aWNv"}}
JSON
}
contas() {
  copiar_banco "$BASE/conta.sqlite3" && contar "$BASE/conta.sqlite3" | awk -F'\t' '$1=="users"{print $2}'
  rm -f "$BASE/conta.sqlite3"
}

log "2. cadastro fechado recusa conta"
codigo="$(registrar)"
[ "$codigo" != 200 ] || falha "o cadastro fechado aceitou uma conta."
[ "$(contas)" = 0 ] || falha "entrou conta com o cadastro fechado."
cadastro_aberto "http://127.0.0.1:$PORTA" && falha "cadastro_aberto disse aberto com o cadastro fechado."

log "3. cadastro aberto aceita a conta de teste; fechado de novo, a conferência passa"
bash "$APP/cofre/scripts/cadastro.sh" abrir || falha "cadastro.sh abrir falhou."
bash "$APP/cofre/scripts/conferir.sh" >/dev/null 2>&1 && falha "a conferência passou com o cadastro aberto."
cadastro_aberto "http://127.0.0.1:$PORTA" || falha "cadastro_aberto não viu o cadastro aberto."
codigo="$(registrar)"
[ "$codigo" = 200 ] || falha "o cadastro aberto recusou a conta ($codigo): $(head -c 300 "$BASE/registro.json")"
[ "$(contas)" = 1 ] || falha "a conta de teste não entrou."
bash "$APP/cofre/scripts/cadastro.sh" fechar || falha "cadastro.sh fechar falhou."

log "4. painel /admin desligado; config.json e SIGNUPS_ALLOWED no .env são acusados"
echo '{"signups_allowed": true}' >"$DADOS/config.json"
bash "$APP/cofre/scripts/conferir.sh" >/dev/null 2>&1 && falha "a conferência passou com config.json."
rm -f "$DADOS/config.json"
echo 'SIGNUPS_ALLOWED=true' >>"$ENV_FILE"
bash "$APP/cofre/scripts/conferir.sh" >/dev/null 2>&1 && falha "a conferência passou com SIGNUPS_ALLOWED no .env."
sed -i.bak '/^SIGNUPS_ALLOWED=/d' "$ENV_FILE" && rm -f "$ENV_FILE.bak"
painel_desligado "http://127.0.0.1:$PORTA" || falha "o painel /admin está ligado."

log "5. backup e ensaio de restauração"
bash "$APP/cofre/scripts/exportar.sh" || falha "exportar.sh falhou."
PACOTE="$(ls -1 "$BASE/cofre/backups"/cofre-*.tar.age | head -n 1)"
[ -n "$PACOTE" ] || falha "o backup não gerou pacote."
if tar -tf "$PACOTE" >/dev/null 2>&1; then falha "o pacote abriu sem a chave (não está cifrado)."; fi
ENSAIO_PASTA="$BASE" bash "$APP/cofre/scripts/ensaiar_restauracao.sh" "$PACOTE" --chave "$BASE/chave/identidade.txt" \
  || falha "o ensaio de restauração falhou."
