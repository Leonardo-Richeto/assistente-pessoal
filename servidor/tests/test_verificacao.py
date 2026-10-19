"""Verificação usada pelo scripts/verificar.sh: consulta só lê e não grava nada."""

import http.server
import threading
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select

from assistente import verificacao
from assistente.config import config
from assistente.modelos import Auditoria, Base, Chamada, Gasto

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def url(tmp_path):
    url = f"sqlite:///{tmp_path / 'verifica.db'}"
    Base.metadata.create_all(create_engine(url))
    return url


@pytest.fixture
def ambiente(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL_LEITURA", url)
    monkeypatch.setenv("DATABASE_URL_ESCRITA", url)
    config.cache_clear()
    yield
    config.cache_clear()


def _contagens(url):
    with create_engine(url).connect() as cx:
        return [cx.execute(select(func.count()).select_from(m)).scalar() for m in (Gasto, Auditoria, Chamada)]


async def test_consulta_leitura_nao_grava(url):
    antes = _contagens(url)
    dados = await verificacao.consulta_leitura(url, TZ)
    assert dados["total"] == "0"
    assert _contagens(url) == antes == [0, 0, 0]


def test_main_sem_http_passa(ambiente, url, capsys):
    assert verificacao.main(["--sem-http"]) == 0
    assert "ok    consulta de leitura pelo MCP" in capsys.readouterr().out
    assert _contagens(url) == [0, 0, 0]


def test_main_falha_sem_banco(monkeypatch, tmp_path, capsys):
    vazio = f"sqlite:///{tmp_path / 'sem-tabelas.db'}"
    monkeypatch.setenv("DATABASE_URL_LEITURA", vazio)
    monkeypatch.setenv("DATABASE_URL_ESCRITA", vazio)
    config.cache_clear()
    try:
        assert verificacao.main(["--sem-http"]) == 1
    finally:
        config.cache_clear()
    assert "FALHA consulta de leitura pelo MCP" in capsys.readouterr().out


class _Respostas(http.server.BaseHTTPRequestHandler):
    codigos: dict[str, int] = {}

    def do_GET(self):  # noqa: N802 (nome do http.server)
        self.send_response(self.codigos.get(self.path, 404))
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def http_local(monkeypatch):
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _Respostas)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("PORTA", str(servidor.server_port))
    yield _Respostas
    servidor.shutdown()


def test_http_com_login_ligado_passa(ambiente, http_local, capsys):
    http_local.codigos = {"/mcp": 401, "/.well-known/oauth-protected-resource/mcp": 200}
    config.cache_clear()
    assert verificacao.main([]) == 0
    assert "GET /mcp sem token = 401" in capsys.readouterr().out


def test_http_sem_login_falha(ambiente, http_local, capsys):
    """/mcp respondendo 200 sem token é o pior caso: login desligado. Tem de falhar."""
    http_local.codigos = {"/mcp": 200, "/.well-known/oauth-protected-resource/mcp": 404}
    config.cache_clear()
    assert verificacao.main([]) == 1
    saida = capsys.readouterr().out
    assert "FALHA GET /mcp sem token = 200 (esperado 401)" in saida
