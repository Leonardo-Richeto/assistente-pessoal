"""Tabela `chamadas` (Passo 8b3): toda chamada de ferramenta, com a origem, sem argumento nem conteúdo.

Mesmo app de verdade de test_registro.py (criar_app com peças falsas em memória), banco em SQLite.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import anyio
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp_types import Implementation
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from assistente import registro, servidor
from assistente.config import Config
from assistente.modelos import Auditoria, Chamada
from test_registro import SEGREDO, SERVIDOR, _alembic, _pecas_falsas, app, recebidas, url  # noqa: F401 (fixtures)

TZ = ZoneInfo("America/Sao_Paulo")
CLIENTE = Implementation(name="claude-ai", version="1.2.3")
CABECALHOS = {"user-agent": "Claude-User/1.0 (iPhone)", "mcp-session-id": "sessao-abc",
              "authorization": f"Bearer {SEGREDO}", "cookie": f"c={SEGREDO}"}
COLUNAS = ("ferramenta", "resultado", "autor", "cliente", "versao_cliente", "sessao", "user_agent",
           "modelo_declarado", "auditoria_id")


@pytest.fixture
def http_simulado(monkeypatch):
    """Requisição HTTP falsa: o registro lê só mcp-session-id e user-agent dela."""
    monkeypatch.setattr(registro, "get_http_request", lambda: SimpleNamespace(headers=CABECALHOS))


def _chamadas(url) -> list[Chamada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Chamada).order_by(Chamada.id)))


def _auditoria(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def _tupla(c: Chamada) -> tuple:
    return tuple(getattr(c, k) for k in COLUNAS)


def _sem_segredo(linhas) -> None:
    for c in linhas:
        assert SEGREDO not in repr({k: getattr(c, k) for k in Chamada.__table__.columns.keys()})


async def test_toda_chamada_vira_linha_com_a_origem(app, url, http_simulado):
    async with Client(app, client_info=CLIENTE) as c:
        await c.call_tool("vault_read_note", {"path": "a.md"})
        await c.call_tool("vault_write_note", {"path": "a.md", "content": SEGREDO})
        r = (await c.call_tool("registrar_gasto", {"valor": 1, "descricao": SEGREDO, "categoria": "y",
                                                   "modelo": "claude-opus-5-5"})).data
        await c.call_tool("desfazer_registro", {"tipo": "gasto", "id": r["id"], "modelo": "Claude Opus 5.5"})
        with pytest.raises(ToolError, match="Unknown tool"):
            await c.call_tool("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"})
        with pytest.raises(ToolError):
            await c.call_tool("vault_patch_note", {"path": "a.md", "oldString": SEGREDO, "newString": "x"})
    aud = {(a.ferramenta, a.acao): a.id for a in _auditoria(url)}
    base = ("anonimo", "claude-ai", "1.2.3", "sessao-abc", "Claude-User/1.0 (iPhone)")
    assert [_tupla(c) for c in _chamadas(url)] == [
        ("vault_read_note", "ok", *base, None, None),
        ("vault_write_note", "ok", *base, None, aud[("vault_write_note", "escrever")]),
        ("registrar_gasto", "ok", *base, "claude-opus-5-5", aud[("registrar_gasto", "criar")]),
        ("desfazer_registro", "ok", *base, "Claude Opus 5.5", aud[("desfazer_registro", "desfazer")]),
        ("vault_delete_note", "negado", *base, None, aud[("vault_delete_note", "escrever")]),
        ("vault_patch_note", "erro", *base, None, aud[("vault_patch_note", "escrever")]),
    ]
    linhas = _chamadas(url)
    assert all(c.momento is not None and c.duracao_ms >= 0 for c in linhas)
    _sem_segredo(linhas)


async def test_cancelada_vira_linha_cancelado(app, url, http_simulado):
    async with Client(app, client_info=CLIENTE) as c:
        with anyio.move_on_after(0.5):
            await c.call_tool("vault_update_frontmatter", {"path": "a.md", "frontmatter": {"x": SEGREDO}})
    with anyio.fail_after(5):
        while not _chamadas(url):
            await anyio.sleep(0.05)
    (linha,) = _chamadas(url)
    escrever = next(a.id for a in _auditoria(url) if a.acao == "escrever")
    assert _tupla(linha) == ("vault_update_frontmatter", "cancelado", "anonimo", "claude-ai", "1.2.3", "sessao-abc",
                             "Claude-User/1.0 (iPhone)", None, escrever)
    _sem_segredo([linha])


async def test_sem_http_a_origem_fica_vazia_menos_o_cliente(app, url):
    async with Client(app) as c:  # cliente em memória: clientInfo padrão do fastmcp, sem cabeçalho
        await c.call_tool("consultar_gastos", {"inicio": "2026-10-01", "fim": "2026-10-31"})
    (linha,) = _chamadas(url)
    assert (linha.cliente, linha.sessao, linha.user_agent, linha.modelo_declarado) == ("mcp", None, None, None)


@pytest.mark.parametrize("modelo,gravado", [
    ("claude-opus-5-5", "claude-opus-5-5"), ("  Opus 5.5  ", "Opus 5.5"), ("a" * 60, "a" * 60),
    ("a" * 61, None), ("", None), ("opus\nFALSO", None), ("opus; drop table", None), ("ópus", None),
    (SEGREDO + "{x}", None),
])
async def test_modelo_declarado_invalido_e_descartado(app, url, modelo, gravado):
    async with Client(app) as c:
        r = await c.call_tool("registrar_ponto", {"tipo": "entrada", "modelo": modelo})
    assert "Desfazer?" in r.data["confirmacao"]  # inválido não derruba a chamada
    assert [c.modelo_declarado for c in _chamadas(url)] == [gravado]


def test_modelo_declarado_valida_o_formato():
    assert registro.modelo_declarado("claude-opus-5-5") == "claude-opus-5-5"
    for ruim in [None, 3, ["x"], "", " ", "a" * 61, "a/b", "a\tb", "<x>"]:
        assert registro.modelo_declarado(ruim) is None


async def test_modelo_pelo_meta_vale_para_as_pecas(app, url, recebidas):
    # Peça pronta não muda de schema: o modelo só entra se o cliente mandar `_meta._modelo`.
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": "a.md", "content": "x"}, meta={"_modelo": "claude-teste"})
        await c.call_tool("vault_write_note", {"path": "b.md", "content": "x"}, meta={"_modelo": "x\ny"})
    assert [c.modelo_declarado for c in _chamadas(url)] == ["claude-teste", None]
    assert [r[1] for r in recebidas] == ["a.md", "b.md"]


async def test_texto_de_fora_e_cortado_e_limpo(app, url, monkeypatch):
    cab = {"user-agent": "U" * 300 + "\n", "mcp-session-id": "s\x00" * 80}
    monkeypatch.setattr(registro, "get_http_request", lambda: SimpleNamespace(headers=cab))
    async with Client(app, client_info=Implementation(name="n\n" * 60, version="v" * 50)) as c:
        await c.call_tool("listar_categorias_gasto", {})
    (linha,) = _chamadas(url)
    assert linha.user_agent == "U" * 200
    assert linha.sessao == "s" * 80
    assert linha.cliente == "n" * 60 and len(linha.versao_cliente) == 40


async def test_falha_ao_gravar_chamada_nao_derruba_nada(app, url, recebidas, monkeypatch, caplog):
    def _quebrado(*_):
        raise OperationalError("INSERT", {}, Exception("banco fora"))

    monkeypatch.setattr(registro.RegistroChamadas, "_inserir_chamada", _quebrado)
    with caplog.at_level(logging.ERROR, logger="assistente.registro"):
        async with Client(app) as c:
            assert (await c.call_tool("vault_read_note", {"path": "a.md"})).data == SEGREDO
            await c.call_tool("vault_write_note", {"path": "a.md", "content": "x"})
            await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})
    assert _chamadas(url) == []
    assert [a.acao for a in _auditoria(url)] == ["escrever", "ok", "criar"]  # a auditoria segue igual
    assert caplog.text.count("Falha ao gravar a chamada") == 3


async def test_consultar_auditoria_filtra_por_tabela_e_acao(app, url):
    async with Client(app) as c:
        await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})
        await c.call_tool("vault_write_note", {"path": "a.md", "content": "x"})
        with pytest.raises(ToolError):
            await c.call_tool("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"})
        todas = (await c.call_tool("consultar_auditoria", {})).data
        vault = (await c.call_tool("consultar_auditoria", {"tabela": "vault"})).data
        negado = (await c.call_tool("consultar_auditoria", {"acao": "negado"})).data
        escrever = (await c.call_tool("consultar_auditoria", {"tabela": "vault", "acao": "escrever", "limite": 1})).data
        gastos_ok = (await c.call_tool("consultar_auditoria", {"tabela": "gastos", "acao": "ok"})).data
        with pytest.raises(ToolError):
            await c.call_tool("consultar_auditoria", {"tabela": "senhas"})
    assert len(todas) == 5
    assert [(a["tabela"], a["acao"]) for a in vault] == [("vault", "negado"), ("vault", "escrever"), ("vault", "ok"),
                                                         ("vault", "escrever")]
    assert [a["ferramenta"] for a in negado] == ["vault_delete_note"]
    assert [(a["ferramenta"], a["acao"]) for a in escrever] == [("vault_delete_note", "escrever")]
    assert gastos_ok == []


async def test_consultar_chamadas_filtra_e_limita(app, url, http_simulado):
    hoje = datetime.now(TZ).date()
    dias = {"inicio": str(hoje - timedelta(days=1)), "fim": str(hoje + timedelta(days=1))}
    async with Client(app, client_info=CLIENTE) as c:
        await c.call_tool("vault_read_note", {"path": "a.md"})
        await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y", "modelo": "opus"})
        todas = (await c.call_tool("consultar_chamadas", dias)).data
        so_gasto = (await c.call_tool("consultar_chamadas", {**dias, "ferramenta": "registrar_gasto"})).data
        outro = (await c.call_tool("consultar_chamadas", {**dias, "cliente": "outro"})).data
        uma = (await c.call_tool("consultar_chamadas", {**dias, "cliente": "claude-ai", "limite": 1})).data
        passado = (await c.call_tool("consultar_chamadas", {"inicio": "2020-01-01", "fim": "2020-01-31"})).data
        with pytest.raises(ToolError):
            await c.call_tool("consultar_chamadas", {**dias, "limite": 201})
        with pytest.raises(ToolError, match="anterior"):
            await c.call_tool("consultar_chamadas", {"inicio": "2026-10-17", "fim": "2026-10-16"})
    # A linha da própria consulta só entra no fim da chamada: ela aparece na consulta seguinte.
    assert [c["ferramenta"] for c in todas] == ["registrar_gasto", "vault_read_note"]
    chaves = {"id", "momento", "ferramenta", "resultado", "autor", "cliente", "versao_cliente", "sessao", "user_agent",
              "modelo_declarado", "duracao_ms", "auditoria_id"}
    assert all(set(c) == chaves for c in todas)
    assert so_gasto[0]["modelo_declarado"] == "opus" and so_gasto[0]["auditoria_id"] == 1
    assert so_gasto[0]["momento"].endswith("-03:00")
    assert outro == [] and passado == []
    assert len(uma) == 1 and uma[0]["ferramenta"] == "consultar_chamadas"


async def test_pelo_http_grava_cliente_sessao_e_user_agent(tmp_path, url, recebidas, monkeypatch, caplog):
    """Caminho de verdade: initialize com clientInfo, sessão do servidor, cabeçalhos HTTP."""
    import httpx2 as httpx

    monkeypatch.setattr(servidor, "create_proxy", _pecas_falsas(recebidas))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(tmp_path))
    app = servidor.criar_app(cfg).http_app()
    cab = {"accept": "application/json, text/event-stream", "user-agent": "Claude-User/9.9",
           "cookie": f"sessao={SEGREDO}", "x-segredo": SEGREDO}
    with caplog.at_level(logging.INFO, logger="assistente"):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
                r = await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "Anthropic/ClaudeAI", "version": "1.0.0"}}})
                assert r.status_code == 200, r.text
                sessao = r.headers["mcp-session-id"]
                cab["mcp-session-id"] = sessao
                await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                r = await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "vault_write_note", "arguments": {"path": "a.md", "content": SEGREDO}}})
                assert r.status_code == 200, r.text
    (linha,) = _chamadas(url)
    assert (linha.ferramenta, linha.resultado, linha.cliente, linha.versao_cliente, linha.sessao, linha.user_agent) == (
        "vault_write_note", "ok", "Anthropic/ClaudeAI", "1.0.0", sessao, "Claude-User/9.9")
    _sem_segredo([linha])
    assert SEGREDO not in caplog.text


def test_migracao_0003_sobe_e_desce_sem_apagar(tmp_path):
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "0002")
    engine = create_engine(url)
    with engine.begin() as cx:
        cx.execute(text("INSERT INTO auditoria (momento, ferramenta, tabela, registro_id, acao, dados) "
                        "VALUES (CURRENT_TIMESTAMP, 'vault_write_note', 'vault', NULL, 'escrever', '{}')"))
    _alembic(url, "upgrade", "0003")
    engine.dispose()
    with engine.begin() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        # O padrão do momento funciona no SQLite (CURRENT_TIMESTAMP), diferente da 0001.
        cx.execute(text("INSERT INTO chamadas (ferramenta, resultado, duracao_ms, auditoria_id) "
                        "VALUES ('vault_write_note', 'ok', 5, 1)"))

    _alembic(url, "downgrade", "0002")
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
        assert cx.execute(text("SELECT ferramenta, resultado, auditoria_id FROM chamadas")).all() == [
            ("vault_write_note", "ok", 1)]
        assert cx.execute(text("SELECT count(*) FROM auditoria")).scalar() == 1

    _alembic(url, "upgrade", "0003")  # reaproveita a tabela que ficou
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        assert cx.execute(text("SELECT count(*) FROM chamadas WHERE momento IS NOT NULL")).scalar() == 1


def test_migracao_0003_da_so_insert_e_select():
    """SQL do Postgres gerado pela 0003 (modo --sql, sem banco): GRANTs explícitos, sem UPDATE nem DELETE."""
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0002:0003", "--sql"], cwd=SERVIDOR, check=True,
                       capture_output=True, text=True,
                       env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})
    sql = [linha.strip().rstrip(";") for linha in r.stdout.splitlines()]
    concessoes = [linha for linha in sql if linha.startswith(("GRANT", "REVOKE"))]
    assert concessoes == [
        "REVOKE ALL ON TABLE chamadas FROM assistente_escrita, assistente_leitura",
        "REVOKE ALL ON SEQUENCE chamadas_id_seq FROM assistente_escrita, assistente_leitura",
        "GRANT SELECT, INSERT ON TABLE chamadas TO assistente_escrita",
        "GRANT USAGE, SELECT ON SEQUENCE chamadas_id_seq TO assistente_escrita",
        "GRANT SELECT ON TABLE chamadas TO assistente_leitura",
    ]
    assert any(linha.startswith("CREATE TABLE chamadas") for linha in sql)
    assert not any(p in linha for linha in concessoes if linha.startswith("GRANT") for p in ("UPDATE", "DELETE", "ALL"))
    # Nenhuma outra tabela é tocada.
    outras = [linha for linha in sql if linha.startswith(("ALTER TABLE", "DROP", "UPDATE", "DELETE"))]
    assert outras == ["UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002'"]


async def test_consultar_chamadas_pagina_por_antes_id(app, url):
    dias = {"inicio": "2020-01-01", "fim": "2099-12-31"}
    async with Client(app, client_info=CLIENTE) as c:
        for _ in range(5):
            await c.call_tool("listar_categorias_gasto", {})
        pagina1 = (await c.call_tool("consultar_chamadas", {**dias, "limite": 2})).data
        pagina2 = (await c.call_tool("consultar_chamadas", {**dias, "limite": 2, "antes_id": pagina1[-1]["id"]})).data
        pagina3 = (await c.call_tool("consultar_chamadas", {**dias, "limite": 2, "antes_id": pagina2[-1]["id"]})).data
        vazia = (await c.call_tool("consultar_chamadas", {**dias, "antes_id": 1})).data
        with pytest.raises(ToolError):
            await c.call_tool("consultar_chamadas", {**dias, "antes_id": 0})
    ids = [x["id"] for x in pagina1 + pagina2 + pagina3]
    assert ids == [5, 4, 3, 2, 1] and pagina3[-1]["id"] == 1 and len(pagina3) == 1
    assert vazia == []


@pytest.mark.parametrize("vazio", ["", "   ", "\t"])
async def test_consultar_chamadas_filtro_vazio_nao_filtra(app, url, vazio):
    dias = {"inicio": "2020-01-01", "fim": "2099-12-31"}
    async with Client(app, client_info=CLIENTE) as c:
        await c.call_tool("listar_categorias_gasto", {})
        await c.call_tool("consultar_gastos", {"inicio": "2026-10-01", "fim": "2026-10-31"})
        sem = (await c.call_tool("consultar_chamadas", dias)).data
        com = (await c.call_tool("consultar_chamadas", {**dias, "ferramenta": vazio, "cliente": vazio})).data
    # Sem filtro, a consulta `com` vê as 2 de antes e a própria consulta `sem`; com filtro real, não veria.
    assert len(sem) == 2 and [x["ferramenta"] for x in com] == ["consultar_chamadas", "consultar_gastos", "listar_categorias_gasto"]


async def test_consultar_chamadas_acha_a_chamada_das_22h_locais(app, url):
    """22h em Brasília = 01h UTC do dia seguinte: o dia local tem de achá-la, e o dia seguinte não."""
    momento = datetime(2026, 10, 18, 1, 0, tzinfo=ZoneInfo("UTC"))  # 2026-10-17 22:00 em America/Sao_Paulo
    with Session(create_engine(url)) as s, s.begin():
        s.add(Chamada(momento=momento, ferramenta="registrar_gasto", resultado="ok", duracao_ms=1))
    async with Client(app, client_info=CLIENTE) as c:
        dia = (await c.call_tool("consultar_chamadas", {"inicio": "2026-10-17", "fim": "2026-10-17"})).data
        seguinte = (await c.call_tool("consultar_chamadas", {"inicio": "2026-10-18", "fim": "2026-10-18"})).data
    assert [x["ferramenta"] for x in dia] == ["registrar_gasto"]
    assert dia[0]["momento"] == "2026-10-17T22:00:00-03:00"
    assert seguinte == []
