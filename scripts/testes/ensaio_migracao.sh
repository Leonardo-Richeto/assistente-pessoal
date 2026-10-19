#!/usr/bin/env bash
# Ensaio de migração com dados SINTÉTICOS, numa pasta descartável (nada de dado real).
#   bash scripts/testes/ensaio_migracao.sh <pasta-vazia-de-teste>
#
# Monta <pasta>/origem com .env de teste (senhas aleatórias, login Google falso, sem Tailscale),
# sobe a stack, grava gastos/ponto/atividade pelas ferramentas MCP e uma nota no vault, exporta
# com --congelar, derruba a origem (como a máquina antiga desligada) e importa em <pasta>/destino.
# Passa se o importar.sh (que chama o verificar.sh) passar e a nota e os registros estiverem lá.
# No fim, a stack do destino fica de pé em 127.0.0.1:${PORTA_HOST}; derrube com:
#   ASSISTENTE_HOME=<pasta>/destino docker compose --env-file <pasta>/destino/.env down
source "$(dirname "$0")/../lib.sh"

[ "$#" -eq 1 ] || { sed -n '2,10p' "$0"; exit 2; }
BASE="$(absoluto "$1")"
pasta_vazia "$BASE" || falha "$BASE precisa estar vazia ou não existir."
ORIGEM="$BASE/origem"
DESTINO="$BASE/destino"
mkdir -p "$ORIGEM/data/postgres" "$ORIGEM/data/sessoes/oauth" "$ORIGEM/vault/00-inbox" "$BASE/chave" "$DESTINO"

aleatorio() { head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48; }

log "chave age de teste"
garantir_imagem_ferramentas
docker run --rm "$IMAGEM_FERRAMENTAS" age-keygen 2>/dev/null >"$BASE/chave/identidade.txt" || falha "age-keygen falhou."
PUBLICA="$(grep -o 'age1[0-9a-z]*' "$BASE/chave/identidade.txt" | head -n 1)"
[ -n "$PUBLICA" ] || falha "não achei a chave pública."

log ".env de teste na origem"
sed -e "s#^ASSISTENTE_HOME=.*#ASSISTENTE_HOME=$(caminho_docker "$ORIGEM")#" \
    -e "s#^COMPOSE_PROJECT_NAME=.*#COMPOSE_PROJECT_NAME=assistente-ensaio#" \
    -e "s#^PORTA_HOST=.*#PORTA_HOST=18000#" \
    -e "s#^SENHA_DONO=.*#SENHA_DONO=$(aleatorio)#" \
    -e "s#^SENHA_LEITURA=.*#SENHA_LEITURA=$(aleatorio)#" \
    -e "s#^SENHA_ESCRITA=.*#SENHA_ESCRITA=$(aleatorio)#" \
    -e "s#^JWT_SIGNING_KEY=.*#JWT_SIGNING_KEY=$(aleatorio)#" \
    -e "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=http://localhost:18000#" \
    -e "s#^GOOGLE_CLIENT_ID=.*#GOOGLE_CLIENT_ID=ensaio.apps.googleusercontent.com#" \
    -e "s#^GOOGLE_CLIENT_SECRET=.*#GOOGLE_CLIENT_SECRET=ensaio-falso#" \
    -e "s#^GOOGLE_EMAILS_PERMITIDOS=.*#GOOGLE_EMAILS_PERMITIDOS=ensaio@example.com#" \
    -e "s#^VAULT_PATH=.*#VAULT_PATH=/vault#" \
    -e "s#^AGE_DESTINATARIO=.*#AGE_DESTINATARIO=$PUBLICA#" \
    "$APP/.env.example" >"$ORIGEM/.env"
printf -- '---\ntipo: nota\n---\n# Nota sintética do ensaio\n\nTexto de teste, sem dado real.\n' >"$ORIGEM/vault/00-inbox/ensaio.md"

export ASSISTENTE_HOME="$ORIGEM"
descobrir_home
conferir_env
log "subindo a origem"
dc_quieto up -d --build || falha "docker compose up na origem falhou."
esperar_saudavel servidor 300 || falha "servidor da origem não ficou saudável."

log "dados sintéticos pelas ferramentas MCP"
dc exec -T servidor python - <<'PY' || falha "não consegui gravar os dados sintéticos."
import asyncio, os
from zoneinfo import ZoneInfo
from fastmcp import Client
from assistente.banco import criar_servidor_banco
from assistente.db import Bancos

async def main():
    b = Bancos.de_urls(os.environ["DATABASE_URL_LEITURA"], os.environ["DATABASE_URL_ESCRITA"])
    async with Client(criar_servidor_banco(b, ZoneInfo("America/Sao_Paulo"))) as c:
        g = (await c.call_tool("registrar_gasto", {"valor": "12.34", "descricao": "Ensaio", "categoria": "teste"})).data
        await c.call_tool("registrar_gasto", {"valor": "5", "descricao": "Ensaio 2", "categoria": "teste"})
        await c.call_tool("desfazer_registro", {"tipo": "gasto", "id": g["id"]})
        await c.call_tool("registrar_ponto", {"tipo": "entrada"})
        await c.call_tool("registrar_atividade", {"descricao": "Ensaio de migração", "nota_vault": "00-inbox/ensaio.md"})
asyncio.run(main())
PY
bash "$APP/scripts/verificar.sh" >/dev/null || falha "verificar.sh falhou na origem, antes de exportar."
ANTES="$(contagens)"
log "contagens na origem:"; printf '%s\n' "$ANTES" | sed 's/^/  /'

log "exportando (congelar)"
bash "$APP/scripts/exportar.sh" --congelar --destino "$BASE/pacotes" || falha "exportar.sh falhou."
PACOTE="$(ls -1 "$BASE/pacotes"/assistente-*.tar.age | tail -n 1)"
log "derrubando a origem (máquina antiga desligada); os dados dela ficam no disco"
dc_quieto down || falha "docker compose down na origem falhou."

log "importando no destino"
export ASSISTENTE_HOME="$DESTINO"
bash "$APP/scripts/importar.sh" "$PACOTE" --chave "$BASE/chave/identidade.txt" || falha "importar.sh falhou."
descobrir_home

[ "$(contagens)" = "$ANTES" ] || falha "contagens do destino diferentes da origem."
cmp -s "$ORIGEM/vault/00-inbox/ensaio.md" "$DESTINO/vault/00-inbox/ensaio.md" || falha "nota do vault diferente no destino."
grep -q "ASSISTENTE_HOME=$(caminho_docker "$DESTINO")" "$ENV_FILE" || falha "ASSISTENTE_HOME do destino não foi reescrito."
pasta_vazia "$DESTINO/data/tailscale" || falha "data/tailscale do destino deveria estar vazia sem --assumir-tailscale."
log "ensaio ok: origem -> pacote -> destino com as mesmas linhas, vault e .env."
