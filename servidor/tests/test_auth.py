"""A trava por login do GitHub e o servidor HTTP exigindo autenticação."""

from unittest.mock import patch

import httpx2 as httpx
import pytest
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider

from assistente.auth import GitHubRestrito
from assistente.config import Config
from assistente.servidor import criar_app


def _provedor():
    return GitHubRestrito(
        logins_permitidos=["LeonardoRicheto"],
        client_id="x", client_secret="y", base_url="https://mcp.exemplo.com", jwt_signing_key="k" * 32,
    )


def _token(login):
    return AccessToken(token="t", client_id="c", scopes=[], claims={"login": login})


@pytest.mark.parametrize("login,aceito", [("leonardoricheto", True), ("LeonardoRicheto", True), ("intruso", False), (None, False)])
async def test_so_login_permitido_passa(login, aceito):
    p = _provedor()
    with patch.object(GitHubProvider, "load_access_token", return_value=_token(login)):
        assert (await p.load_access_token("qualquer") is not None) is aceito


def test_lista_vazia_nao_sobe():
    with pytest.raises(ValueError):
        GitHubRestrito(logins_permitidos=[], client_id="x", client_secret="y",
                       base_url="https://mcp.exemplo.com", jwt_signing_key="k" * 32)


async def test_endpoint_exige_token(tmp_path):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    cfg = Config(database_url_leitura=url, database_url_escrita=url, public_base_url="https://mcp.exemplo.com",
                 github_client_id="x", github_client_secret="y", github_logins_permitidos="leonardoricheto",
                 jwt_signing_key="k" * 32, _env_file=None)
    app = criar_app(cfg).http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             headers={"accept": "application/json, text/event-stream"})
            assert r.status_code == 401
            meta = await c.get("/.well-known/oauth-protected-resource/mcp")
            assert meta.status_code == 200
            assert "https://mcp.exemplo.com" in meta.text
