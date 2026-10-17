"""Testes das ferramentas de domínio com um cliente MCP real em memória.

Por padrão usa SQLite. Para rodar contra Postgres: TEST_DATABASE_URL=postgresql+psycopg://...
"""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine

from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from assistente.modelos import Base

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def servidor(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'teste.db'}"
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return criar_servidor_banco(Bancos.de_urls(url, url), TZ)


async def chamar(servidor, nome, **args):
    async with Client(servidor) as c:
        return (await c.call_tool(nome, args)).data


async def test_lista_ferramentas(servidor):
    async with Client(servidor) as c:
        nomes = {t.name for t in await c.list_tools()}
    assert {"registrar_gasto", "consultar_gastos", "registrar_ponto", "consultar_ponto",
            "registrar_atividade", "consultar_atividades", "desfazer_registro", "consultar_auditoria"} <= nomes
    assert not any("sql" in n for n in nomes)


async def test_gasto_registra_consulta_e_desfaz(servidor):
    r = await chamar(servidor, "registrar_gasto", valor="42.9", descricao="Feira", categoria=" Mercado ", data="2026-10-15")
    assert "R$ 42,90" in r["confirmacao"] and "Desfazer?" in r["confirmacao"]
    await chamar(servidor, "registrar_gasto", valor=10, descricao="Café", categoria="lazer", data="2026-10-16")

    c = await chamar(servidor, "consultar_gastos", inicio="2026-10-01", fim="2026-10-31")
    assert c["total"] == "52.90"
    assert c["por_categoria"] == {"mercado": "42.90", "lazer": "10.00"}

    await chamar(servidor, "desfazer_registro", tipo="gasto", id=r["id"])
    c = await chamar(servidor, "consultar_gastos", inicio="2026-10-01", fim="2026-10-31")
    assert c["total"] == "10.00"

    aud = await chamar(servidor, "consultar_auditoria")
    assert [a["acao"] for a in aud] == ["desfazer", "criar", "criar"]


async def test_gasto_rejeita_valor_invalido(servidor):
    with pytest.raises(ToolError):
        await chamar(servidor, "registrar_gasto", valor=-5, descricao="x", categoria="y")


async def test_ponto_calcula_horas_com_pausa(servidor):
    for tipo, hora in [("entrada", "08:00"), ("pausa_inicio", "12:00"), ("pausa_fim", "13:00"), ("saida", "17:30")]:
        await chamar(servidor, "registrar_ponto", tipo=tipo, momento=f"2026-10-15T{hora}:00")
    c = await chamar(servidor, "consultar_ponto", inicio="2026-10-15", fim="2026-10-15")
    assert c["horas_por_dia"] == {"2026-10-15": 8.5}
    assert c["registros"][0]["momento"].startswith("2026-10-15T08:00")


async def test_diario_busca(servidor):
    await chamar(servidor, "registrar_atividade", descricao="Revisei o PR do gateway", tags=["Trabalho"])
    await chamar(servidor, "registrar_atividade", descricao="Corrida no parque", tags=["saude"])
    hoje = datetime.now(TZ).date()
    achados = await chamar(servidor, "consultar_atividades", inicio=str(hoje - timedelta(days=1)), fim=str(hoje), busca="trabalho")
    assert [a["descricao"] for a in achados] == ["Revisei o PR do gateway"]


async def test_categorias_ignoram_gasto_desfeito(servidor):
    # Decisão do Leonardo (2026-10-17): categoria só de gasto desfeito não aparece.
    r = await chamar(servidor, "registrar_gasto", valor=1, descricao="teste", categoria="teste")
    await chamar(servidor, "registrar_gasto", valor=5, descricao="Pão", categoria="mercado")
    await chamar(servidor, "registrar_gasto", valor=7, descricao="Leite", categoria="mercado")
    assert await chamar(servidor, "listar_categorias_gasto") == ["mercado", "teste"]
    await chamar(servidor, "desfazer_registro", tipo="gasto", id=r["id"])
    assert await chamar(servidor, "listar_categorias_gasto") == ["mercado"]
