"""Gera `ferramentas_pecas.json`: os nomes reais das ferramentas das peças prontas.

Roda DENTRO da imagem do servidor, onde `mcpvault` e `paperless-mcp` estão
instalados na versão fixada do Dockerfile. Não precisa de Paperless real nem do
vault: usa uma pasta temporária vazia e URL/token falsos (a listagem não conecta).
Da raiz do repo:

    docker compose exec -T servidor python - < servidor/tests/fixtures/gerar_ferramentas_pecas.py \
        > servidor/tests/fixtures/ferramentas_pecas.json

Rode de novo sempre que mudar a versão de uma peça no Dockerfile e revise o diff:
ferramenta nova fica escondida até entrar em `PERMITIDAS` (segura) ou `BLOQUEADAS` (apaga,
sobrescreve ou expõe dados); o teste falha enquanto não tiver decisão.
"""

import asyncio
import json
import os
import subprocess
import tempfile

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

PAPERLESS_FALSO = {"PAPERLESS_URL": "http://127.0.0.1:1", "PAPERLESS_TOKEN": "falso", "PATH": os.environ["PATH"]}


async def _nomes(transport) -> list[str]:
    async with Client(transport, timeout=60) as c:
        return [t.name for t in await c.list_tools()]


def _versao(comando: str) -> str:
    return subprocess.run([comando, "--version"], capture_output=True, text=True, check=True).stdout.split()[-1]


async def main() -> None:
    with tempfile.TemporaryDirectory() as vazio:
        vault = await _nomes(StdioTransport(command="mcpvault", args=[vazio]))
    padrao = await _nomes(StdioTransport(command="paperless-mcp", args=["--stdio"], env=PAPERLESS_FALSO))
    completo = await _nomes(StdioTransport(
        command="paperless-mcp", args=["--stdio"], env={**PAPERLESS_FALSO, "PAPERLESS_MCP_ENABLE_DELETE": "true"}))
    print(json.dumps({
        "mcpvault": {"versao": _versao("mcpvault"), "ferramentas": sorted(vault)},
        "paperless-mcp": {
            "versao": _versao("paperless-mcp"),
            "ferramentas": sorted(completo),
            "so_com_enable_delete": sorted(set(completo) - set(padrao)),
        },
    }, indent=2, ensure_ascii=False))


asyncio.run(main())
