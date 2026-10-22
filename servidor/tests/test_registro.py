"""Registro de toda chamada de ferramenta (assistente/registro.py, Passos 8b e 8b2).

O app é o de verdade (criar_app), com o create_proxy de verdade sobre peças falsas em memória
que guardam o que receberam. Banco em SQLite.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anyio
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from fastmcp.server.auth import AccessToken
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from assistente import banco, registro, servidor, vault
from assistente.auth import GitHubRestrito, GoogleRestrito
from assistente.config import Config
from assistente.modelos import Auditoria, Base

SEGREDO = "TEXTO-SECRETO-DA-NOTA"
SERVIDOR = Path(__file__).parent.parent


def _pecas_falsas(recebidas: list):
    """Peças falsas com os nomes e parâmetros reais (schemas lidos no container, 2026-10-17)."""
    vault = FastMCP("mcpvault")

    @vault.tool
    def write_note(path: str, content: str, frontmatter: dict | None = None, mode: str = "overwrite") -> str:
        recebidas.append(("write_note", path, content))
        return "ok"

    @vault.tool
    def patch_note(path: str, oldString: str, newString: str) -> str:
        recebidas.append(("patch_note", path))
        raise ToolError("oldString não encontrado")

    @vault.tool
    def read_note(path: str) -> str:
        return SEGREDO

    @vault.tool
    def read_multiple_notes(paths: list[str]) -> str:
        return SEGREDO

    @vault.tool
    def manage_tags(path: str, operation: str, tags: list[str] | None = None) -> str:
        recebidas.append(("manage_tags", path, operation))
        return "ok"

    @vault.tool
    async def update_frontmatter(path: str, frontmatter: dict) -> str:
        recebidas.append(("update_frontmatter", path))
        await anyio.sleep_forever()  # simula escrita que é cancelada no meio
        return "ok"

    @vault.tool
    def delete_note(path: str, confirmPath: str) -> str:
        recebidas.append(("delete_note", path))
        return "apagou"

    paperless = FastMCP("paperless-mcp")

    @paperless.tool
    def update_document(document_id: int, title: str | None = None) -> str:
        recebidas.append(("update_document", document_id, title))
        return "ok"

    @paperless.tool
    def create_share_link(document_id: int) -> str:
        recebidas.append(("create_share_link", document_id))
        return "https://vazou"

    def _proxy(config: dict):
        (ns, alvo), = config["mcpServers"].items()
        return create_proxy({"vault": vault, "paperless": paperless}[ns])

    return _proxy


@pytest.fixture
def recebidas():
    return []


@pytest.fixture
def url(tmp_path):
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    return url


@pytest.fixture
def app(tmp_path, monkeypatch, recebidas, url):
    monkeypatch.setattr(servidor, "create_proxy", _pecas_falsas(recebidas))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(tmp_path), paperless_url="http://127.0.0.1:1", paperless_api_key="falso")
    return servidor.criar_app(cfg)


def _linhas(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def _token(claims: dict):
    return lambda: AccessToken(token="t", client_id="cliente", scopes=[], claims=claims)


def _ligadas(linhas: list[Auditoria]) -> list[tuple]:
    """(acao, índice da linha `escrever` ligada pelo registro_id, ou None)."""
    pos = {a.id: i for i, a in enumerate(linhas)}
    return [(a.acao, pos.get(a.registro_id) if a.registro_id is not None else None) for a in linhas]


async def test_escrita_no_vault_grava_caminho_sem_conteudo(app, url, recebidas, caplog):
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("vault_write_note", {"path": "00-inbox/teste.md", "mode": "append", "content": SEGREDO,
                                                   "frontmatter": {"titulo": SEGREDO}})
    assert recebidas == [("write_note", "00-inbox/teste.md", SEGREDO)]
    linhas = _linhas(url)
    assert [(a.ferramenta, a.tabela, a.acao, a.registro_id, a.dados, a.autor) for a in linhas] == [
        ("vault_write_note", "vault", "escrever", None, {"caminho": "00-inbox/teste.md"}, "anonimo"),
        ("vault_write_note", "vault", "ok", linhas[0].id, {"caminho": "00-inbox/teste.md"}, "anonimo"),
    ]
    assert all(a.momento is not None for a in linhas)
    assert SEGREDO not in repr([(a.dados, a.ferramenta, a.autor) for a in linhas])
    assert SEGREDO not in caplog.text


async def test_escrita_que_falha_grava_erro(app, url, recebidas):
    async with Client(app) as c:
        with pytest.raises(ToolError):
            await c.call_tool("vault_patch_note", {"path": "a.md", "oldString": SEGREDO, "newString": "x"})
    linhas = _linhas(url)
    assert [(a.acao, a.dados) for a in linhas] == [("escrever", {"caminho": "a.md"}), ("erro", {"caminho": "a.md"})]
    assert _ligadas(linhas) == [("escrever", None), ("erro", 0)]


async def test_escrita_do_paperless_grava_so_ids(app, url, recebidas):
    async with Client(app) as c:
        await c.call_tool("paperless_update_document", {"document_id": 7, "title": SEGREDO})
    linhas = _linhas(url)
    assert [(a.ferramenta, a.tabela, a.acao, a.dados) for a in linhas] == [
        ("paperless_update_document", "paperless", "escrever", {"document_id": 7}),
        ("paperless_update_document", "paperless", "ok", {"document_id": 7}),
    ]
    assert _ligadas(linhas) == [("escrever", None), ("ok", 0)]
    assert SEGREDO not in repr([a.dados for a in linhas])


def test_ids_do_paperless_so_inteiros():
    args = {"document_id": 7, "id": 3, "tag_ids": [1, "2", True, 4, *range(30)], "title": SEGREDO,
            "content": SEGREDO, "correspondent_name": SEGREDO, "task_id": SEGREDO, "custom_field_id": "9",
            "archive_serial_number": 12, "is_inbox_tag": True, "parent_id": False, "x" * 70 + "_id": 1}
    dados = registro.ids_do_paperless(args)
    assert dados == {"document_id": 7, "id": 3, "tag_ids": [1, 4, *range(16)]}
    assert SEGREDO not in repr(dados)


async def test_leitura_so_vai_para_o_log(app, url, caplog):
    with caplog.at_level(logging.INFO, logger="assistente.registro"):
        async with Client(app) as c:
            await c.call_tool("vault_read_note", {"path": "00-inbox/onde-parei.md"})
            await c.call_tool("vault_read_multiple_notes", {"paths": ["a.md", "b.md"]})
            await c.call_tool("vault_manage_tags", {"path": "a.md", "operation": "list"})
            await c.call_tool("consultar_gastos", {"inicio": "2026-10-01", "fim": "2026-10-31"})
    assert _linhas(url) == []
    # Leitura loga em DEBUG: com o logger em INFO (padrão do servidor), nem caminho nem autor aparecem.
    assert "Chamada" not in caplog.text and "onde-parei" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="assistente.registro"):
        async with Client(app) as c:
            await c.call_tool("vault_read_note", {"path": "00-inbox/onde-parei.md"})
            await c.call_tool("vault_read_multiple_notes", {"paths": ["a.md", "b.md"]})
            await c.call_tool("consultar_gastos", {"inicio": "2026-10-01", "fim": "2026-10-31"})
    assert "Chamada vault_read_note: ok autor=anonimo {'caminho': '00-inbox/onde-parei.md'}" in caplog.text
    assert "'caminhos': ['a.md', 'b.md']" in caplog.text
    assert "Chamada consultar_gastos: ok" in caplog.text
    assert all(r.levelno == logging.DEBUG for r in caplog.records if r.getMessage().startswith("Chamada"))
    assert SEGREDO not in caplog.text


async def test_escrita_continua_em_info(app, caplog):
    with caplog.at_level(logging.INFO, logger="assistente.registro"):
        async with Client(app) as c:
            await c.call_tool("vault_write_note", {"path": "a.md", "mode": "append", "content": SEGREDO})
            await c.call_tool("registrar_gasto", {"valor": 10, "descricao": "pão", "categoria": "mercado"})
    for nome in ("vault_write_note", "registrar_gasto"):
        regs = [r for r in caplog.records if r.getMessage().startswith(f"Chamada {nome}:")]
        assert regs and all(r.levelno == logging.INFO for r in regs), nome
    assert SEGREDO not in caplog.text


async def test_leitura_com_erro_vai_para_info_sem_dados(app, url, caplog):
    """Passo 8e: leitura que falha aparece no log INFO, só com o nome e o resultado; leitura ok continua em DEBUG."""
    with caplog.at_level(logging.DEBUG, logger="assistente.registro"):
        async with Client(app) as c:
            with pytest.raises(ToolError):
                await c.call_tool("consultar_gastos", {"inicio": "2026-10-31", "fim": "2026-10-01"})
            await c.call_tool("consultar_gastos", {"inicio": "2026-10-01", "fim": "2026-10-31"})
    regs = [r for r in caplog.records if r.getMessage().startswith("Chamada consultar_gastos")]
    assert [(r.levelno, r.getMessage().split(" autor=")[0]) for r in regs] == [
        (logging.INFO, "Chamada consultar_gastos: erro"), (logging.DEBUG, "Chamada consultar_gastos: ok")]
    assert "autor=" not in regs[0].getMessage()
    assert _linhas(url) == []


@pytest.mark.parametrize("situacao", ["erro", "erro_no_resultado", "cancelado"])
async def test_leitura_de_peca_com_erro_ou_cancelada_loga_sem_caminho_nem_conta(url, caplog, monkeypatch, situacao):
    from assistente.db import Bancos

    monkeypatch.setattr(registro, "identidade", lambda: "ela@gmail.com")
    mw = registro.RegistroChamadas(Bancos.de_urls(url, url), leituras={"vault_read_note"}, auditadas=set())
    entrou = anyio.Event()

    async def _peca(context):
        entrou.set()
        if situacao == "erro":
            raise ToolError("nota não existe")
        if situacao == "erro_no_resultado":
            return SimpleNamespace(is_error=True)
        await anyio.sleep_forever()

    contexto = _contexto("vault_read_note", {"path": "00-inbox/segredo.md"})
    with caplog.at_level(logging.DEBUG, logger="assistente.registro"):
        if situacao == "cancelado":
            with anyio.CancelScope() as escopo:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(mw.on_call_tool, contexto, _peca)
                    await entrou.wait()
                    escopo.cancel()
        elif situacao == "erro":
            with pytest.raises(ToolError):
                await mw.on_call_tool(contexto, _peca)
        else:
            await mw.on_call_tool(contexto, _peca)
    esperado = "cancelado" if situacao == "cancelado" else "erro"
    regs = [r for r in caplog.records if r.getMessage().startswith("Chamada")]
    assert [(r.levelno, r.getMessage()) for r in regs] == [(logging.INFO, f"Chamada vault_read_note: {esperado}")]
    assert "segredo.md" not in caplog.text and "ela@gmail.com" not in caplog.text
    assert _linhas(url) == []  # leitura não vai para a auditoria


async def test_manage_tags_que_muda_e_escrita(app, url):
    async with Client(app) as c:
        await c.call_tool("vault_manage_tags", {"path": "a.md", "operation": "add", "tags": ["x"]})
    assert [a.acao for a in _linhas(url)] == ["escrever", "ok"]


async def test_bloqueada_e_inexistente_gravam_negado(app, url, recebidas):
    async with Client(app) as c:
        for nome, args in [("vault_delete_note", {"path": "00-inbox/x.md", "confirmPath": "00-inbox/x.md"}),
                           ("paperless_create_share_link", {"document_id": 1}),
                           ("apagar_tudo", {"conteudo": SEGREDO})]:
            with pytest.raises(ToolError, match="Unknown tool"):
                await c.call_tool(nome, args)
    assert recebidas == []
    linhas = _linhas(url)
    # Fora das leituras conhecidas = escrita: `escrever` antes, `negado` depois, ligadas.
    assert [(a.ferramenta, a.tabela, a.acao, a.dados) for a in linhas] == [
        ("vault_delete_note", "vault", "escrever", {"caminho": "00-inbox/x.md"}),
        ("vault_delete_note", "vault", "negado", {"caminho": "00-inbox/x.md"}),
        ("paperless_create_share_link", "paperless", "escrever", {"document_id": 1}),
        ("paperless_create_share_link", "paperless", "negado", {"document_id": 1}),
        ("apagar_tudo", "ferramenta", "escrever", {}),
        ("apagar_tudo", "ferramenta", "negado", {}),
    ]
    assert _ligadas(linhas) == [("escrever", None), ("negado", 0), ("escrever", None), ("negado", 2),
                                ("escrever", None), ("negado", 4)]


async def test_leitura_de_peca_nao_montada_grava_so_negado(tmp_path, url, recebidas, monkeypatch):
    monkeypatch.setattr(servidor, "create_proxy", _pecas_falsas(recebidas))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(tmp_path))
    async with Client(servidor.criar_app(cfg)) as c:
        with pytest.raises(ToolError, match="Unknown tool"):
            await c.call_tool("paperless_get_document", {"document_id": 1})
    assert [(a.acao, a.registro_id) for a in _linhas(url)] == [("negado", None)]


async def test_nome_fora_das_listas_que_executa_grava_escrever(app, url):
    # Ferramenta nova que ninguém classificou (ex.: posta direto no app): conta como escrita.
    app.tool(lambda texto: "feito", name="ferramenta_nova")
    async with Client(app) as c:
        assert (await c.call_tool("ferramenta_nova", {"texto": SEGREDO})).content[0].text == "feito"
    linhas = _linhas(url)
    assert [(a.ferramenta, a.tabela, a.acao, a.dados) for a in linhas] == [
        ("ferramenta_nova", "ferramenta", "escrever", {}), ("ferramenta_nova", "ferramenta", "ok", {})]
    assert _ligadas(linhas) == [("escrever", None), ("ok", 0)]


async def test_caminho_por_hash_do_fastmcp_grava_escrever(app, url):
    # FastMCP 4.1.0 (server.py:1455-1461) aceita `<hash12>_<nome>` para ferramenta visível a apps.
    # O nome com hash não está em lista nenhuma: conta como escrita, mesmo que o nome local seja leitura.
    meta = {"fastmcp": {"tool_hash": "0123456789ab"}, "ui": {"visibility": ["app", "model"]}}
    app.tool(lambda: "feito", name="consultar_gastos_app", meta=meta)
    async with Client(app) as c:
        assert (await c.call_tool("0123456789ab_consultar_gastos_app", {})).content[0].text == "feito"
        with pytest.raises(ToolError, match="Unknown tool"):
            await c.call_tool("abcdefabcdef_vault_read_note", {"path": "a.md"})
    assert [(a.ferramenta, a.acao) for a in _linhas(url)] == [
        ("0123456789ab_consultar_gastos_app", "escrever"), ("0123456789ab_consultar_gastos_app", "ok"),
        ("abcdefabcdef_vault_read_note", "escrever"), ("abcdefabcdef_vault_read_note", "negado")]


def test_ferramentas_do_banco_estao_classificadas():
    nomes = {t.name for t in anyio.run(banco.criar_servidor_banco(None, None).list_tools)}
    assert nomes == banco.LEITURAS_BANCO | banco.ESCRITAS_BANCO
    assert not banco.LEITURAS_BANCO & banco.ESCRITAS_BANCO


async def test_escrita_do_banco_nao_duplica_a_auditoria(app, url):
    async with Client(app) as c:
        r = (await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})).data
        await c.call_tool("desfazer_registro", {"tipo": "gasto", "id": r["id"]})
    assert [(a.ferramenta, a.acao) for a in _linhas(url)] == [("registrar_gasto", "criar"), ("desfazer_registro", "desfazer")]


@pytest.mark.parametrize("nome", ["x" * 61, "vault_write_note\nFALSO", "vault_write_note;rm", "nota-nova", "ação"])
async def test_nome_invalido_nao_vai_cru_para_log_nem_banco(app, url, recebidas, caplog, nome):
    with caplog.at_level(logging.INFO, logger="assistente.registro"):
        async with Client(app) as c:
            with pytest.raises(ToolError, match="Unknown tool"):
                await c.call_tool(nome, {"path": "a.md", "content": SEGREDO})
    assert recebidas == []
    assert [(a.ferramenta, a.tabela, a.acao, a.dados) for a in _linhas(url)] == [
        ("<nome invalido>", "ferramenta", "escrever", {}), ("<nome invalido>", "ferramenta", "negado", {})]
    mensagens = [r.getMessage() for r in caplog.records if r.name == "assistente.registro"]
    assert mensagens and all(nome not in m for m in mensagens)
    assert any("<nome invalido>" in m for m in mensagens)


def test_nome_seguro():
    assert registro.nome_seguro("vault_write_note") == "vault_write_note"
    assert registro.nome_seguro("a" * 60) == "a" * 60
    for ruim in ["", "a" * 61, "a b", "a\nb", "a/b", None, 3]:
        assert registro.nome_seguro(ruim) == "<nome invalido>"


def _contexto(nome: str, argumentos: dict):
    return SimpleNamespace(message=SimpleNamespace(name=nome, arguments=argumentos))


async def test_cancelamento_no_meio_da_escrita_grava_cancelado(url):
    """CancelledError não é Exception: a linha `cancelado` precisa sair mesmo dentro do escopo cancelado."""
    from assistente.db import Bancos

    mw = registro.RegistroChamadas(Bancos.de_urls(url, url), leituras=set(), auditadas=set())
    entrou = anyio.Event()

    async def _escreve_e_trava(context):
        entrou.set()  # aqui a peça já pode ter escrito
        await anyio.sleep_forever()

    with anyio.CancelScope() as escopo:
        async with anyio.create_task_group() as tg:
            tg.start_soon(mw.on_call_tool, _contexto("vault_write_note", {"path": "a.md", "mode": "append", "content": SEGREDO}),
                          _escreve_e_trava)
            await entrou.wait()
            escopo.cancel()
    assert escopo.cancelled_caught
    linhas = _linhas(url)
    assert [(a.ferramenta, a.acao, a.dados) for a in linhas] == [
        ("vault_write_note", "escrever", {"caminho": "a.md"}), ("vault_write_note", "cancelado", {"caminho": "a.md"})]
    assert _ligadas(linhas) == [("escrever", None), ("cancelado", 0)]


async def test_cancelamento_pelo_cliente_grava_cancelado(app, url, recebidas):
    """Caminho de verdade: a sessão fecha com a escrita em andamento; o servidor cancela a chamada."""
    async with Client(app) as c:
        with anyio.move_on_after(0.5):
            await c.call_tool("vault_update_frontmatter", {"path": "a.md", "frontmatter": {"x": SEGREDO}})
    with anyio.fail_after(5):
        while len(_linhas(url)) < 2:
            await anyio.sleep(0.05)
    assert recebidas == [("update_frontmatter", "a.md")]
    assert _ligadas(_linhas(url)) == [("escrever", None), ("cancelado", 0)]


@pytest.mark.parametrize("claims,autor", [
    # Só vale o claim gravado por auth.py depois da lista; email/login soltos não contam.
    ({"identidade": "leonardoricheto", "email": "publico@exemplo.com", "login": "LeonardoRicheto"}, "leonardoricheto"),
    ({"identidade": "ela@gmail.com", "email": "ela@gmail.com"}, "ela@gmail.com"),
])
async def test_identidade_do_token_vai_para_a_auditoria(app, url, monkeypatch, claims, autor):
    monkeypatch.setattr(registro, "get_access_token", _token(claims))
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": "a.md", "mode": "append", "content": "x"})
        with pytest.raises(ToolError):
            await c.call_tool("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"})
        await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})
    assert [(a.acao, a.autor) for a in _linhas(url)] == [
        ("escrever", autor), ("ok", autor), ("escrever", autor), ("negado", autor), ("criar", autor)]


async def test_token_sem_identidade_conferida_e_anonimo(app, url, monkeypatch):
    monkeypatch.setattr(registro, "get_access_token", _token({"email": "x@gmail.com", "login": "x"}))
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": "a.md", "mode": "append", "content": "x"})
        await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})
    assert [(a.acao, a.autor) for a in _linhas(url)] == [("escrever", "anonimo"), ("ok", "anonimo"), ("criar", None)]


@pytest.mark.parametrize("provedor,claims,esperada", [
    ("github", {"login": "LeonardoRicheto", "email": "publico@exemplo.com"}, "leonardoricheto"),
    ("google", {"email": "Ela@gmail.com", "email_verified": "true", "login": "outro"}, "ela@gmail.com"),
])
async def test_load_access_token_grava_a_identidade_conferida(provedor, claims, esperada):
    comum = dict(client_id="x", client_secret="y", base_url="https://mcp.exemplo.com", jwt_signing_key="k" * 32)
    from fastmcp.server.auth.providers.github import GitHubProvider
    from fastmcp.server.auth.providers.google import GoogleProvider

    if provedor == "github":
        p, base = GitHubRestrito(logins_permitidos=["leonardoricheto"], **comum), GitHubProvider
    else:
        p, base = GoogleRestrito(emails_permitidos=["ela@gmail.com"], **comum), GoogleProvider
    original = AccessToken(token="t", client_id="c", scopes=[], claims=dict(claims))
    with patch.object(base, "load_access_token", return_value=original):
        acesso = await p.load_access_token("qualquer")
    assert acesso.claims["identidade"] == esperada
    assert "identidade" not in original.claims  # não mexe no objeto do provedor


async def test_sem_token_autor_e_anonimo(app, url, monkeypatch):
    monkeypatch.setattr(registro, "get_access_token", lambda: None)
    async with Client(app) as c:
        with pytest.raises(ToolError):
            await c.call_tool("nao_existe", {})
    assert [a.autor for a in _linhas(url)] == ["anonimo", "anonimo"]


async def test_falha_ao_gravar_auditoria_recusa_a_escrita(app, url, recebidas, monkeypatch):
    def _quebrado(*_):
        raise OperationalError("INSERT", {}, Exception("banco fora"))

    monkeypatch.setattr(registro.RegistroChamadas, "_inserir", _quebrado)
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Escrita recusada"):
            await c.call_tool("vault_write_note", {"path": "a.md", "mode": "append", "content": SEGREDO})
        with pytest.raises(ToolError, match="Escrita recusada"):
            await c.call_tool("paperless_update_document", {"document_id": 1})
        # Fora das leituras conhecidas também é recusado (falha fechado); leitura não depende do banco.
        with pytest.raises(ToolError, match="Escrita recusada"):
            await c.call_tool("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"})
        with pytest.raises(ToolError, match="Escrita recusada"):
            await c.call_tool("ferramenta_nova", {})
        assert (await c.call_tool("vault_read_note", {"path": "a.md"})).data == SEGREDO
    assert recebidas == []


async def test_consultar_auditoria_mostra_as_linhas_novas(app, url):
    async with Client(app) as c:
        await c.call_tool("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})
        await c.call_tool("vault_write_note", {"path": "a.md", "mode": "append", "content": SEGREDO})
        with pytest.raises(ToolError):
            await c.call_tool("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"})
        aud = (await c.call_tool("consultar_auditoria", {})).data
    assert [a["acao"] for a in aud] == ["negado", "escrever", "ok", "escrever", "criar"]
    chaves = {"id", "momento", "ferramenta", "tabela", "registro_id", "acao", "dados", "autor"}
    assert all(set(a) == chaves for a in aud)
    # ids: 1 criar (registro_id = gasto 1), 2 escrever, 3 ok -> 2, 4 escrever, 5 negado -> 4.
    assert [a["registro_id"] for a in aud] == [4, None, 2, None, 1]
    assert SEGREDO not in repr(aud)


def test_caminhos_do_vault_ignora_conteudo():
    args = {"path": "a" * 400, "content": SEGREDO, "oldString": SEGREDO, "frontmatter": {"x": SEGREDO},
            "paths": ["b.md", 3, *[f"{i}.md" for i in range(30)]], "query": SEGREDO}
    dados = registro.caminhos_do_vault(args)
    assert set(dados) == {"caminho", "caminhos"}
    assert len(dados["caminho"]) == 300 and len(dados["caminhos"]) == 19
    assert registro.caminhos_do_vault({"oldPath": "a.md", "newPath": "b.md"}) == {"caminho": "a.md", "destino": "b.md"}
    assert SEGREDO not in repr(dados)


# Classificação revisada à mão, nome por nome (Passo 8e; item 8 do revisor do 8b). Não depende do prefixo do nome:
# "get_document_ai_suggestions" poderia gravar algo e "run_saved_view" soa como ação. Ferramenta nova numa peça
# ou no banco só passa no teste depois de alguém decidir aqui se ela lê ou escreve. Na dúvida, escrita
# (falha fechado: grava `escrever` antes da chamada).
LE, ESCREVE = "leitura", "escrita"
CLASSIFICACAO_REVISADA = {
    # mcpvault 0.16.0
    "vault_read_note": LE, "vault_read_note_lines": LE, "vault_read_multiple_notes": LE, "vault_search_notes": LE,
    "vault_list_directory": LE, "vault_get_note_outline": LE, "vault_get_notes_info": LE,
    "vault_get_frontmatter": LE, "vault_get_vault_stats": LE, "vault_list_all_tags": LE,
    "buscar_vault": LE,  # nossa (vault.py): índice em memória das notas; só lê
    "ler_nota": LE, "notas_recentes": LE,  # nossas (vault.py): só lêem
    "escrever_nota": ESCREVE,  # nossa (vault.py): troca a nota inteira, só com a versão lida
    "historico_nota": LE,  # nossa (vault.py): git log da nota; só lê
    "restaurar_nota": ESCREVE,  # nossa (vault.py): grava o conteúdo de uma versão antiga como versão nova
    "vault_wiki_link": LE,  # lê a nota pelo nome (basename) e devolve o conteúdo; não escreve
    "vault_write_note": ESCREVE, "vault_patch_note": ESCREVE, "vault_update_frontmatter": ESCREVE,
    "vault_manage_tags": ESCREVE,  # operation=list é leitura, conferido em registro.py na hora da chamada
    # paperless-mcp 0.1.0: leitura
    "paperless_search_documents": LE, "paperless_search_everywhere": LE, "paperless_search_autocomplete": LE,
    "paperless_get_document": LE, "paperless_get_document_content": LE, "paperless_get_document_metadata": LE,
    "paperless_get_document_notes": LE, "paperless_get_document_history": LE,
    "paperless_find_similar_documents": LE, "paperless_download_document": LE,
    "paperless_get_document_thumbnail": LE, "paperless_get_next_asn": LE,
    "paperless_get_document_suggestions": LE,
    "paperless_get_document_ai_suggestions": LE,  # devolve sugestões; não aplica nada no documento
    "paperless_list_tags": LE, "paperless_list_correspondents": LE, "paperless_list_document_types": LE,
    "paperless_list_storage_paths": LE, "paperless_list_custom_fields": LE, "paperless_list_trash": LE,
    "paperless_list_active_tasks": LE, "paperless_list_tasks": LE, "paperless_get_task": LE,
    "paperless_get_paperless_info": LE, "paperless_get_statistics": LE, "paperless_get_system_status": LE,
    "paperless_list_saved_views": LE, "paperless_get_saved_view": LE,
    "paperless_run_saved_view": LE,  # roda a busca salva; só lê documentos
    "paperless_list_share_links": LE,
    # paperless-mcp 0.1.0: escrita
    "paperless_upload_document": ESCREVE, "paperless_add_document_note": ESCREVE, "paperless_create_tag": ESCREVE,
    "paperless_create_correspondent": ESCREVE, "paperless_create_document_type": ESCREVE,
    "paperless_create_storage_path": ESCREVE, "paperless_create_custom_field": ESCREVE,
    "paperless_restore_documents": ESCREVE, "paperless_acknowledge_tasks": ESCREVE,
    "paperless_delete_share_link": ESCREVE, "paperless_update_document": ESCREVE, "paperless_update_tag": ESCREVE,
    "paperless_update_correspondent": ESCREVE, "paperless_update_document_type": ESCREVE,
    "paperless_update_storage_path": ESCREVE, "paperless_update_custom_field": ESCREVE,
    "paperless_set_document_custom_field": ESCREVE, "paperless_remove_document_custom_field": ESCREVE,
    "paperless_bulk_rotate_documents": ESCREVE,
    # banco (código nosso)
    "consultar_gastos": LE, "listar_categorias_gasto": LE, "consultar_ponto": LE, "consultar_atividades": LE,
    "consultar_auditoria": LE, "consultar_chamadas": LE,
    "registrar_gasto": ESCREVE, "registrar_ponto": ESCREVE, "registrar_atividade": ESCREVE,
    "desfazer_registro": ESCREVE, "vincular_nota": ESCREVE,
    "marcar_desatualizada": ESCREVE,  # grava a marca no banco; não mexe na nota
    "consultar_desatualizadas": LE,
    "consultar_sessoes": LE,  # lê a tabela sessoes (Passo 11); sem comandos
}


def test_cada_permitida_esta_em_uma_lista_so():
    assert servidor.PERMITIDAS == servidor.LEITURAS_PECAS | servidor.ESCRITAS_PECAS
    for nome in servidor.PERMITIDAS:
        assert (nome in servidor.LEITURAS_PECAS) + (nome in servidor.ESCRITAS_PECAS) == 1, nome
    assert not banco.LEITURAS_BANCO & banco.ESCRITAS_BANCO


def test_classificacao_bate_com_a_revisao_nome_por_nome():
    """Cada nome visível (peças e banco) foi revisado à mão; sem revisão, o teste falha (sem olhar prefixo)."""
    leituras = servidor.LEITURAS_PECAS | banco.LEITURAS_BANCO | vault.LEITURAS_VAULT
    escritas = servidor.ESCRITAS_PECAS | banco.ESCRITAS_BANCO | vault.ESCRITAS_VAULT
    sem_revisao = sorted((leituras | escritas) - CLASSIFICACAO_REVISADA.keys())
    assert not sem_revisao, f"Classifique à mão em CLASSIFICACAO_REVISADA: {sem_revisao}"
    sobrando = sorted(CLASSIFICACAO_REVISADA.keys() - leituras - escritas)
    assert not sobrando, f"Revisados que não existem mais nas listas: {sobrando}"
    divergentes = {n: c for n, c in CLASSIFICACAO_REVISADA.items() if (n in leituras) != (c == LE)}
    assert not divergentes, f"Lista diferente da revisão: {divergentes}"
    assert not servidor.BLOQUEADAS & CLASSIFICACAO_REVISADA.keys()


def _alembic(url: str, *args: str) -> None:
    # Em subprocesso: o env.py do Alembic reconfigura o logging (fileConfig) e afetaria os outros testes.
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=SERVIDOR, check=True, capture_output=True,
                   env={**os.environ, "DATABASE_URL_MIGRACAO": url, "PYTHONIOENCODING": "utf-8"})


def _registro_id_aceita_vazio(engine) -> bool:
    return next(c for c in inspect(engine).get_columns("auditoria") if c["name"] == "registro_id")["nullable"]


def test_migracao_sobe_e_desce_sem_apagar(tmp_path):
    # SQLite não tem now(), o padrão de `momento` na 0001: os INSERTs mandam o momento.
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "0001")
    engine = create_engine(url)
    assert not _registro_id_aceita_vazio(engine)
    with engine.begin() as cx:
        cx.execute(text("INSERT INTO auditoria (momento, ferramenta, tabela, registro_id, acao, dados) "
                        "VALUES (CURRENT_TIMESTAMP, 'registrar_gasto', 'gastos', 5, 'criar', '{}')"))

    _alembic(url, "upgrade", "head")
    engine.dispose()
    assert _registro_id_aceita_vazio(engine)
    with engine.begin() as cx:
        cx.execute(text("INSERT INTO auditoria (momento, ferramenta, tabela, registro_id, acao, dados) "
                        "VALUES (CURRENT_TIMESTAMP, 'vault_write_note', 'vault', NULL, 'ok', '{}')"))

    # Com linha sem registro_id, a descida é recusada e a auditoria fica intacta (nada de UPDATE).
    with pytest.raises(subprocess.CalledProcessError) as erro:
        _alembic(url, "downgrade", "0001")
    assert "Downgrade da 0002 recusado" in erro.value.stderr.decode()
    engine.dispose()
    assert _registro_id_aceita_vazio(engine)
    with engine.connect() as cx:
        assert cx.execute(text("SELECT ferramenta, registro_id FROM auditoria ORDER BY id")).all() == [
            ("registrar_gasto", 5), ("vault_write_note", None)]

    # Sem linha vazia, a descida funciona e não muda nenhuma linha.
    with engine.begin() as cx:
        cx.execute(text("DELETE FROM auditoria WHERE registro_id IS NULL"))  # só no banco de teste
    _alembic(url, "downgrade", "0001")
    engine.dispose()
    assert not _registro_id_aceita_vazio(engine)
    with engine.connect() as cx:
        assert cx.execute(text("SELECT ferramenta, registro_id FROM auditoria ORDER BY id")).all() == [
            ("registrar_gasto", 5)]

    _alembic(url, "upgrade", "head")
    engine.dispose()
    assert _registro_id_aceita_vazio(engine)


def test_migracao_0002_desce_offline_e_recusada():
    """Em modo --sql não há banco para contar as linhas vazias: a descida é recusada (Passo 8e, como a 0004)."""
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0002:0001", "--sql"], cwd=SERVIDOR,
                       capture_output=True, text=True,
                       env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})
    assert r.returncode != 0
    assert "Downgrade da 0002 não roda em modo --sql" in r.stderr
    assert "SET NOT NULL" not in r.stdout


@pytest.mark.parametrize("provedor,claims,autor", [
    ("google", {"email": "ela@gmail.com", "email_verified": "true"}, "ela@gmail.com"),
    # GitHub com e-mail público no token: vale o login conferido na lista, não o e-mail.
    ("github", {"login": "LeonardoRicheto", "email": "publico@exemplo.com"}, "leonardoricheto"),
])
async def test_identidade_pelo_http_com_token_do_provedor(tmp_path, url, recebidas, monkeypatch, provedor, claims, autor):
    """Caminho de verdade: Bearer → _Restrito.load_access_token → middleware lê o token da requisição."""
    import httpx2 as httpx
    from fastmcp.server.auth.providers.github import GitHubProvider
    from fastmcp.server.auth.providers.google import GoogleProvider

    monkeypatch.setattr(servidor, "create_proxy", _pecas_falsas(recebidas))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, vault_path=str(tmp_path),
                 public_base_url="https://mcp.exemplo.com", auth_provedor=provedor,
                 google_client_id="x", google_client_secret="y", google_emails_permitidos="ela@gmail.com",
                 github_client_id="x", github_client_secret="y", github_logins_permitidos="leonardoricheto",
                 jwt_signing_key="k" * 32)
    escopos = {"google": ["openid", "https://www.googleapis.com/auth/userinfo.email"], "github": ["user"]}[provedor]
    token = AccessToken(token="t", client_id="c", scopes=escopos, resource="https://mcp.exemplo.com/mcp", claims=claims)
    base = {"google": GoogleProvider, "github": GitHubProvider}[provedor]
    app = servidor.criar_app(cfg).http_app()
    cab = {"accept": "application/json, text/event-stream", "authorization": "Bearer qualquer"}
    chamadas = [("vault_write_note", {"path": "a.md", "mode": "append", "content": SEGREDO}),
                ("vault_delete_note", {"path": "a.md", "confirmPath": "a.md"}),
                ("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"})]
    with patch.object(base, "load_access_token", return_value=token):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
                r = await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "teste", "version": "1"}}})
                assert r.status_code == 200, r.text
                if sessao := r.headers.get("mcp-session-id"):
                    cab["mcp-session-id"] = sessao
                await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                for i, (nome, args) in enumerate(chamadas):
                    r = await c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                                                                "params": {"name": nome, "arguments": args}})
                    assert r.status_code == 200, r.text
    assert [(a.ferramenta, a.acao, a.autor) for a in _linhas(url)] == [
        ("vault_write_note", "escrever", autor), ("vault_write_note", "ok", autor),
        ("vault_delete_note", "escrever", autor), ("vault_delete_note", "negado", autor),
        ("registrar_gasto", "criar", autor)]
