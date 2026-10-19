"""Verificação de saúde usada por scripts/verificar.sh. Roda dentro do container do servidor.

Só lê. A consulta passa pelas ferramentas MCP do banco (cliente em memória) com o usuário de
LEITURA nos dois papéis, sem o middleware de registro: nada é gravado, nem em `chamadas`.
O HTTP local confere que o login está ligado (/mcp sem token = 401).

    python -m assistente.verificacao            # consulta + HTTP
    python -m assistente.verificacao --sem-http # só a consulta
Sai com 0 se tudo passou, 1 se algo falhou.
"""

import argparse
import asyncio
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from fastmcp import Client

from .banco import criar_servidor_banco
from .config import config
from .db import Bancos

# O que cada caminho precisa responder sem token.
ESPERADO_HTTP = {"/mcp": 401, "/.well-known/oauth-protected-resource/mcp": 200}


async def consulta_leitura(url_leitura: str, tz: ZoneInfo) -> dict:
    """Chama `consultar_gastos` de hoje pelo MCP em memória, só com o usuário de leitura."""
    servidor = criar_servidor_banco(Bancos.de_urls(url_leitura, url_leitura), tz)
    hoje = datetime.now(tz).date().isoformat()
    async with Client(servidor) as c:
        return (await c.call_tool("consultar_gastos", {"inicio": hoje, "fim": hoje})).data


def status_http(url: str, timeout: float = 10) -> int:
    """Código HTTP de um GET sem token (erro HTTP também é resposta)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--sem-http", action="store_true", help="não confere o HTTP local")
    opcoes = args.parse_args(argv)

    cfg = config()
    falhas = 0

    try:
        dados = asyncio.run(consulta_leitura(cfg.database_url_leitura, cfg.tz))
        print(f"ok    consulta de leitura pelo MCP (gastos de hoje: total {dados['total']})")
    except Exception as e:  # qualquer falha aqui é falha da verificação
        print(f"FALHA consulta de leitura pelo MCP: {type(e).__name__}: {e}")
        falhas += 1

    if not opcoes.sem_http:
        base = f"http://127.0.0.1:{cfg.porta}"
        for caminho, esperado in ESPERADO_HTTP.items():
            try:
                obtido = status_http(base + caminho)
            except Exception as e:
                print(f"FALHA GET {caminho}: {type(e).__name__}: {e}")
                falhas += 1
                continue
            if obtido == esperado:
                print(f"ok    GET {caminho} sem token = {obtido}")
            else:
                print(f"FALHA GET {caminho} sem token = {obtido} (esperado {esperado})")
                falhas += 1

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
