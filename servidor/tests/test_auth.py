"""A trava por login (GitHub e Google), o registro de clientes e o servidor HTTP exigindo token."""

import time
from unittest.mock import AsyncMock, patch

import httpx2 as httpx
import pytest
from pydantic import ValidationError
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import ClientCode
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


@pytest.mark.parametrize("url_publica", ["https://maquina.tailnet.ts.net", "https://mcp.exemplo.com"])
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


def test_redirects_somam_ao_padrao_do_claude(tmp_path):
    assert _cfg(tmp_path).auth_redirects_permitidos == REDIRECTS_CLAUDE
    assert _cfg(tmp_path, auth_redirects_permitidos="").auth_redirects_permitidos == REDIRECTS_CLAUDE
    assert _cfg(tmp_path, auth_redirects_permitidos=" https://a.exemplo/cb , https://b.exemplo/cb").auth_redirects_permitidos \
        == [*REDIRECTS_CLAUDE, "https://a.exemplo/cb", "https://b.exemplo/cb"]
    # Repetir o do claude.ai não duplica.
    assert _cfg(tmp_path, auth_redirects_permitidos=REDIRECTS_CLAUDE[0]).auth_redirects_permitidos == REDIRECTS_CLAUDE


@pytest.mark.parametrize("padrao", [
    "https://evil.example", "https://evil.example/", "https://evil.example/*", "https://evil.example//**",
    "evil.example/cb", "https:///cb",
    # Sem https, ou com curinga do fnmatch / query / fragmento no caminho.
    "http://ok.exemplo/cb", "ftp://ok.exemplo/cb", "https://ok.exemplo/cb?x=1", "https://ok.exemplo/c?b",
    "https://ok.exemplo/cb#x", "https://ok.exemplo/[a-z]b", "https://ok.exemplo/cb]",
])
def test_redirect_sem_caminho_nao_sobe(tmp_path, padrao):
    with pytest.raises(ValidationError, match="AUTH_REDIRECTS_PERMITIDOS"):
        _cfg(tmp_path, auth_redirects_permitidos=f"https://ok.exemplo/cb,{padrao}")


async def test_redirect_extra_soma_no_registro(tmp_path):
    app = criar_app(_cfg(tmp_path, auth_redirects_permitidos="https://a.exemplo/cb")).http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            for redirect, esperado in [("https://a.exemplo/cb", 201), (REDIRECTS_CLAUDE[0], 201),
                                       ("https://a.exemplo/outro", 400)]:
                r = await c.post("/register", json={"redirect_uris": [redirect], "client_name": "teste",
                                                    "token_endpoint_auth_method": "none"})
                assert r.status_code == esperado, (redirect, r.text)


# Ficha 9: o ChatGPT só entra na instância que soma os callbacks dele no .env (a da Nathalia).
CALLBACKS_CHATGPT = "https://chatgpt.com/connector_platform_oauth_redirect,https://chatgpt.com/connector/oauth/*"


@pytest.mark.parametrize("extra,aceito", [(CALLBACKS_CHATGPT, True), ("", False)])
async def test_registro_aceita_chatgpt_so_com_os_callbacks_no_env(tmp_path, extra, aceito):
    app = criar_app(_cfg(tmp_path, auth_redirects_permitidos=extra)).http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            for redirect in ["https://chatgpt.com/connector_platform_oauth_redirect",
                             "https://chatgpt.com/connector/oauth/abc123"]:
                r = await c.post("/register", json={"redirect_uris": [redirect], "client_name": "teste",
                                                    "token_endpoint_auth_method": "none"})
                assert r.status_code == (201 if aceito else 400), (redirect, r.text)
            r = await c.post("/register", json={"redirect_uris": ["https://chatgpt.com/outro"], "client_name": "teste",
                                                "token_endpoint_auth_method": "none"})
            assert r.status_code == 400


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


# Sem DCR: o cliente manda o client id do Google direto e o FastMCP cria um cliente na hora
# (oauth_proxy/proxy.py, get_client). Só a lista de redirects segura.
DESAFIO_PKCE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("provedor", ["github", "google"])
@pytest.mark.parametrize("redirect,codigo", [
    ("https://evil.example/cb", 400),
    ("https://claude.ai.evil.example/api/mcp/auth_callback", 400),
    ("https://claude.ai/api/mcp/auth_callback", 302),
])
async def test_authorize_com_client_id_do_provedor(tmp_path, provedor, redirect, codigo):
    cfg = _cfg(tmp_path, provedor)
    app = criar_app(cfg).http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            r = await c.get("/authorize", params={
                "client_id": getattr(cfg, f"{provedor}_client_id"), "redirect_uri": redirect, "response_type": "code",
                "code_challenge": DESAFIO_PKCE, "code_challenge_method": "S256", "state": "s"})
    assert r.status_code == codigo, r.text
    if codigo == 302:
        assert r.headers["location"].startswith("https://mcp.exemplo.com/consent")
    else:
        assert "evil" not in r.headers.get("location", "")


def _respostas_google(tokeninfo: dict, userinfo: dict | None):
    """Simula o tokeninfo e o userinfo do Google como o GoogleTokenVerifier os chama."""
    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com" and req.url.path == "/tokeninfo":
            return httpx.Response(200, json=tokeninfo)
        if req.url.path == "/oauth2/v2/userinfo":
            return httpx.Response(200, json=userinfo) if userinfo is not None else httpx.Response(500)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


def _tokeninfo(**extra):
    return {"aud": "x", "sub": "123", "scope": "openid https://www.googleapis.com/auth/userinfo.email",
            "expires_in": "3599", **extra}


@pytest.mark.parametrize("tokeninfo,userinfo,aceito", [
    (_tokeninfo(email="ela@gmail.com", email_verified="true"), None, True),
    (_tokeninfo(email="Ela@Gmail.com", email_verified="true"), {"email": "ela@gmail.com", "verified_email": True}, True),
    (_tokeninfo(email="ela@gmail.com", email_verified="false"), None, False),
    # tokeninfo diz "false" em texto; o userinfo não salva (o FastMCP usa o primeiro que vier).
    (_tokeninfo(email="ela@gmail.com", email_verified="false"), {"email": "ela@gmail.com", "verified_email": True}, False),
    # Sem email_verified no tokeninfo, vale o booleano do userinfo.
    (_tokeninfo(email="ela@gmail.com"), {"email": "ela@gmail.com", "verified_email": True}, True),
    (_tokeninfo(email="ela@gmail.com"), {"email": "ela@gmail.com", "verified_email": False}, False),
    (_tokeninfo(email="ela@gmail.com"), None, False),
    (_tokeninfo(), {"email": "ela@gmail.com", "verified_email": True}, True),
    (_tokeninfo(email="outra@gmail.com", email_verified="true"), None, False),
    (_tokeninfo(aud="outro-app", email="ela@gmail.com", email_verified="true"), None, False),
])
async def test_google_respostas_reais_passam_pela_lista(tokeninfo, userinfo, aceito):
    p = _google()
    verificador = p._token_validator
    verificador._http_client = _respostas_google(tokeninfo, userinfo)

    # O OAuthProxy troca o JWT pelo token do Google e chama o verificador; aqui pulamos só a troca.
    async def _carregar(self, token):
        return await verificador.verify_token("token-do-google")

    with patch.object(GoogleProvider, "load_access_token", _carregar):
        assert (await p.load_access_token("jwt") is not None) is aceito


# Troca do código por token (POST /token). O código guarda o token do provedor; o FastMCP 4.1.0
# emite o JWT sem olhar a lista. Aqui a conta tem de estar na lista antes de qualquer token.
VERIFICADOR_PKCE = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636, apêndice B: gera DESAFIO_PKCE
PERMITIDA = {"github": "LeonardoRicheto", "google": "Ela@Gmail.com"}


def _validado(provedor, conta):
    """Resposta do verificador do provedor (GitHub /user ou tokeninfo do Google) para a conta."""
    if conta in (None, "erro"):
        return None
    claims = {"login": conta} if provedor == "github" else {"email": conta, "email_verified": "true"}
    return AccessToken(token="tok-do-provedor", client_id="x", scopes=[], claims=claims)


async def _guardar_codigo(auth, client_id: str) -> str:
    agora = time.time()
    await auth._code_store.put(key="codigo-1", ttl=300, value=ClientCode(
        code="codigo-1", client_id=client_id, redirect_uri=REDIRECTS_CLAUDE[0], code_challenge=DESAFIO_PKCE,
        code_challenge_method="S256", scopes=[], expires_at=agora + 300, created_at=agora,
        idp_tokens={"access_token": "tok-do-provedor", "token_type": "Bearer", "expires_in": 3599}))
    return "codigo-1"


@pytest.mark.parametrize("provedor", ["github", "google"])
@pytest.mark.parametrize("conta,aceito", [
    ("permitida", True),
    ("intruso@gmail.com", False),
    (None, False),     # o provedor recusou o token
    ("erro", False),   # o provedor não respondeu
])
async def test_troca_do_codigo_so_para_conta_permitida(tmp_path, provedor, conta, aceito):
    servidor = criar_app(_cfg(tmp_path, provedor))
    auth = servidor.auth
    conta = PERMITIDA[provedor] if conta == "permitida" else conta
    verificar = AsyncMock(return_value=_validado(provedor, conta))
    if conta == "erro":
        verificar.side_effect = httpx.ConnectError("provedor fora")
    app = servidor.http_app()
    original = OAuthProxy.exchange_authorization_code
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.exemplo.com") as c:
            r = await c.post("/register", json={"redirect_uris": [REDIRECTS_CLAUDE[0]], "client_name": "teste",
                                                "token_endpoint_auth_method": "none"})
            cid = r.json()["client_id"]
            codigo = await _guardar_codigo(auth, cid)
            with patch.object(auth._token_validator, "verify_token", verificar), \
                 patch.object(OAuthProxy, "exchange_authorization_code", autospec=True, side_effect=original) as emitir:
                r = await c.post("/token", data={
                    "grant_type": "authorization_code", "code": codigo, "redirect_uri": REDIRECTS_CLAUDE[0],
                    "client_id": cid, "code_verifier": VERIFICADOR_PKCE})
                _, ttl = await auth._client_store.ttl(key=cid)
                if aceito:
                    assert r.status_code == 200, r.text
                    assert emitir.called
                    assert ttl is None  # cliente em uso não expira
                    assert await auth.load_access_token(r.json()["access_token"]) is not None
                else:
                    # invalid_grant; o FastMCP responde 401 (regra do MCP para token inválido).
                    assert r.status_code == 401, r.text
                    assert r.json()["error"] == "invalid_grant"
                    assert "access_token" not in r.json()
                    assert not emitir.called  # nenhum token emitido nem gravado
                    assert ttl is not None and ttl > 0  # o cliente mantém o prazo
                    assert await auth._code_store.get(key=codigo) is None  # código apagado
                    verificar.assert_awaited_with("tok-do-provedor")  # conferiu no provedor
                    # Repetir o mesmo código não adianta.
                    r = await c.post("/token", data={
                        "grant_type": "authorization_code", "code": codigo, "redirect_uri": REDIRECTS_CLAUDE[0],
                        "client_id": cid, "code_verifier": VERIFICADOR_PKCE})
                    assert r.status_code == 401 and not emitir.called
