"""A trava por login (GitHub e Google), o registro de clientes e o servidor HTTP exigindo token."""

from unittest.mock import patch

import httpx2 as httpx
import pytest
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider

from assistente.auth import GitHubRestrito, GoogleRestrito
from fastmcp.server.auth.providers.google import GoogleProvider
from assistente.config import REDIRECTS_CLAUDE, Config
from assistente.servidor import _auth, criar_app


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


def _google():
    return GoogleRestrito(emails_permitidos=["Ela@Gmail.com"], client_id="x", client_secret="y",
                          base_url="https://mcp.exemplo.com", jwt_signing_key="k" * 32)


# O GoogleProvider (FastMCP 4.1.0) põe em email_verified o texto do tokeninfo ("true"/"false")
# ou, sem ele, o booleano do userinfo. Só "verdadeiro" passa.
@pytest.mark.parametrize("claims,aceito", [
    ({"email": "ela@gmail.com", "email_verified": True}, True),
    ({"email": "ela@gmail.com", "email_verified": "true"}, True),
    ({"email": "ELA@gmail.com", "email_verified": "true"}, True),
    ({"email": "ela@gmail.com"}, False),
    ({"email": "ela@gmail.com", "email_verified": None}, False),
    ({"email": "ela@gmail.com", "email_verified": False}, False),
    ({"email": "ela@gmail.com", "email_verified": "false"}, False),
    ({"email": "ela@gmail.com", "email_verified": ""}, False),
    ({"email": "outra@gmail.com", "email_verified": True}, False),
    ({"email_verified": True}, False),
    ({}, False),
])
async def test_google_so_email_permitido_passa(claims, aceito):
    p = _google()
    tok = AccessToken(token="t", client_id="c", scopes=[], claims=claims)
    with patch.object(GoogleProvider, "load_access_token", return_value=tok):
        assert (await p.load_access_token("qualquer") is not None) is aceito


def test_lista_vazia_nao_sobe():
    with pytest.raises(ValueError):
        GitHubRestrito(logins_permitidos=[], client_id="x", client_secret="y",
                       base_url="https://mcp.exemplo.com", jwt_signing_key="k" * 32)


@pytest.mark.parametrize("url_publica", ["https://<maquina>.<tailnet>.ts.net", "https://mcp.exemplo.com"])
def test_auth_desativada_nao_sobe_com_url_publica(tmp_path, url_publica):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    cfg = Config(database_url_leitura=url, database_url_escrita=url, public_base_url=url_publica,
                 auth_desativada=True, _env_file=None)
    with pytest.raises(SystemExit):
        _auth(cfg)


@pytest.mark.parametrize("chave", ["", "x", "k" * 31])
def test_chave_jwt_curta_nao_sobe(tmp_path, chave):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    cfg = Config(database_url_leitura=url, database_url_escrita=url, public_base_url="https://mcp.exemplo.com",
                 auth_provedor="google", google_client_id="x", google_client_secret="y",
                 google_emails_permitidos="ela@gmail.com", jwt_signing_key=chave, _env_file=None)
    with pytest.raises(SystemExit):
        _auth(cfg)


@pytest.mark.parametrize("provedor", ["github", "google"])
async def test_endpoint_exige_token(tmp_path, provedor):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    cfg = Config(database_url_leitura=url, database_url_escrita=url, public_base_url="https://mcp.exemplo.com",
                 auth_provedor=provedor,
                 github_client_id="x", github_client_secret="y", github_logins_permitidos="leonardoricheto",
                 google_client_id="x", google_client_secret="y", google_emails_permitidos="ela@gmail.com",
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


def _cfg(tmp_path, provedor="google", **extra):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    return Config(database_url_leitura=url, database_url_escrita=url, public_base_url="https://mcp.exemplo.com",
                  auth_provedor=provedor,
                  github_client_id="x", github_client_secret="y", github_logins_permitidos="leonardoricheto",
                  google_client_id="x", google_client_secret="y", google_emails_permitidos="ela@gmail.com",
                  jwt_signing_key="k" * 32, _env_file=None, **extra)


def test_redirects_padrao_sao_do_claude(tmp_path):
    assert _cfg(tmp_path).auth_redirects_permitidos == REDIRECTS_CLAUDE
    assert _cfg(tmp_path, auth_redirects_permitidos="").auth_redirects_permitidos == REDIRECTS_CLAUDE
    assert _cfg(tmp_path, auth_redirects_permitidos=" https://a.exemplo/cb , https://b.exemplo/cb").auth_redirects_permitidos \
        == ["https://a.exemplo/cb", "https://b.exemplo/cb"]


@pytest.mark.parametrize("provedor", ["github", "google"])
@pytest.mark.parametrize("redirect,aceito", [
    ("https://claude.ai/api/mcp/auth_callback", True),
    ("https://claude.com/api/mcp/auth_callback", True),
    ("https://evil.example/cb", False),
    ("https://claude.ai.evil.example/api/mcp/auth_callback", False),
    ("https://claude.ai/outro", False),
    ("http://localhost:3000/callback", False),
])
async def test_registro_so_aceita_redirect_do_claude(tmp_path, monkeypatch, provedor, redirect, aceito):
    import fastmcp
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path / "fastmcp")  # não grava no home de verdade
    app = criar_app(_cfg(tmp_path, provedor)).http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            r = await c.post("/register", json={"redirect_uris": [redirect], "client_name": "teste",
                                                "token_endpoint_auth_method": "none"})
            assert (r.status_code == 201) is aceito, r.text
