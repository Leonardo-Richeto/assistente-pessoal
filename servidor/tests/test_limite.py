"""Limites por IP e globais nos endpoints do login, e prazo dos clientes registrados no volume oauth."""

import asyncio
import logging
from unittest.mock import patch

import fastmcp
import httpx2 as httpx
import pytest
from pydantic import ValidationError

from assistente import limite
from assistente.config import REDIRECTS_CLAUDE, Config
from assistente.limite import LimiteRequisicoes, gateway_padrao
from assistente.servidor import criar_app

REGISTRO = {"redirect_uris": [REDIRECTS_CLAUDE[0]], "client_name": "teste", "token_endpoint_auth_method": "none"}
AUTORIZAR = {"client_id": "x", "redirect_uri": REDIRECTS_CLAUDE[0], "response_type": "code", "state": "s",
             "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", "code_challenge_method": "S256"}


def _cfg(tmp_path, **extra):
    url = f"sqlite:///{tmp_path / 'a.db'}"
    return Config(database_url_leitura=url, database_url_escrita=url, public_base_url="https://mcp.exemplo.com",
                  auth_provedor="google", google_client_id="x", google_client_secret="y",
                  google_emails_permitidos="ela@gmail.com", jwt_signing_key="k" * 32, _env_file=None, **extra)


def _cliente(app, ip="127.0.0.1"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="https://mcp.exemplo.com")


async def test_register_passa_do_limite_e_recebe_429(tmp_path):
    app = criar_app(_cfg(tmp_path, limite_register_por_hora=3)).http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            # Pedido recusado também conta: quem testa redirect errado gasta a cota.
            errado = {**REGISTRO, "redirect_uris": ["https://evil.example/cb"]}
            codigos = [(await c.post("/register", json=corpo)).status_code for corpo in (REGISTRO, errado, REGISTRO)]
            assert codigos == [201, 400, 201]
            r = await c.post("/register", json=REGISTRO)
            assert r.status_code == 429
            assert int(r.headers["retry-after"]) > 0
            assert r.json()["error"] == "too_many_requests"
            # Outro IP, pelo proxy local (X-Forwarded-For), tem a própria cota.
            r = await c.post("/register", json=REGISTRO, headers={"x-forwarded-for": "203.0.113.7"})
            assert r.status_code == 201
            # O limite não vale para o resto: metadata segue respondendo.
            assert (await c.get("/.well-known/oauth-protected-resource/mcp")).status_code == 200


async def test_authorize_passa_do_limite_e_recebe_429(tmp_path):
    app = criar_app(_cfg(tmp_path, limite_authorize_por_hora=2)).http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            ip = {"x-forwarded-for": "198.51.100.1"}
            assert [(await c.get("/authorize", params=AUTORIZAR, headers=ip)).status_code for _ in range(2)] == [302, 302]
            assert (await c.get("/authorize", params=AUTORIZAR, headers=ip)).status_code == 429
            assert (await c.post("/register", json=REGISTRO, headers=ip)).status_code == 201


async def test_consent_passa_do_limite_e_recebe_429(tmp_path):
    # Cada GET /consent grava um CSRF no volume oauth (oauth_proxy/consent.py); vale o limite do /authorize.
    app = criar_app(_cfg(tmp_path, limite_authorize_por_hora=2)).http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            r = await c.get("/authorize", params=AUTORIZAR)
            assert r.status_code == 302
            consentir = r.headers["location"].removeprefix("https://mcp.exemplo.com")
            assert consentir.startswith("/consent")
            assert [(await c.get(consentir)).status_code for _ in range(2)] == [200, 200]
            assert (await c.get(consentir)).status_code == 429
            assert (await c.post("/consent", data={})).status_code == 429  # POST divide a mesma cota


@pytest.mark.parametrize("caminho", ["/token", "/auth/callback"])
async def test_token_e_callback_tem_limite(tmp_path, caminho):
    app = criar_app(_cfg(tmp_path, limite_token_por_hora=2)).http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            pedir = (lambda: c.post(caminho, data={"grant_type": "authorization_code", "code": "x"})) \
                if caminho == "/token" else (lambda: c.get(caminho, params={"code": "x", "state": "y"}))
            codigos = [(await pedir()).status_code for _ in range(3)]
            assert 429 not in codigos[:2] and codigos[2] == 429


async def test_teto_global_segura_quem_troca_de_ip(tmp_path):
    app = criar_app(_cfg(tmp_path, limite_register_por_hora=10, limite_global_register_por_hora=3)).http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            # Blocos /64 diferentes dentro do mesmo /48: cada um tem cota própria por IP.
            ips = [f"2001:db8:1:{i}::1" for i in range(5)]
            codigos = [(await c.post("/register", json=REGISTRO, headers={"x-forwarded-for": ip})).status_code
                       for ip in ips]
            assert codigos == [201, 201, 201, 429, 429]
            r = await c.post("/register", json=REGISTRO, headers={"x-forwarded-for": "203.0.113.50"})
            assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
            # O teto é por caminho: /authorize segue com a cota dele.
            assert (await c.get("/authorize", params=AUTORIZAR)).status_code == 302


async def test_teto_global_nao_zera_quando_esquece_ips(monkeypatch):
    # Com IPs demais, o mapa por IP esquece os antigos; o teto global continua contando.
    monkeypatch.setattr(limite, "MAX_CHAVES", 2)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    m = LimiteRequisicoes(app, limites={"/register": 1}, globais={"/register": 4}, confiaveis=["127.0.0.1"])

    async def status(ip):
        enviados = []

        async def send(msg):
            enviados.append(msg)

        await m({"type": "http", "path": "/register", "client": ("127.0.0.1", 1),
                 "headers": [(b"x-forwarded-for", ip.encode())]}, None, send)
        return enviados[0]["status"]

    codigos = [await status(f"198.51.100.{i}") for i in range(6)]
    assert codigos == [200, 200, 200, 200, 429, 429]
    assert len(m.vistos) <= 2


def test_limites_padrao_e_invalidos(tmp_path):
    cfg = _cfg(tmp_path)
    assert (cfg.limite_register_por_hora, cfg.limite_authorize_por_hora, cfg.limite_token_por_hora,
            cfg.limite_global_register_por_hora, cfg.limite_global_authorize_por_hora,
            cfg.clientes_ttl_dias) == (10, 30, 60, 100, 300, 1)
    for campo in ["limite_register_por_hora", "limite_authorize_por_hora", "limite_token_por_hora",
                  "limite_global_register_por_hora", "limite_global_authorize_por_hora", "clientes_ttl_dias"]:
        with pytest.raises(ValidationError):
            _cfg(tmp_path, **{campo: 0})
    with pytest.raises(ValidationError):
        _cfg(tmp_path, proxies_confiaveis="127.0.0.1,nao-e-ip")
    assert _cfg(tmp_path, proxies_confiaveis=" 172.20.0.1 , 10.0.0.0/8").proxies_confiaveis == ["172.20.0.1", "10.0.0.0/8"]


def _scope(par, *xff):
    return {"type": "http", "path": "/register", "client": (par, 1),
            "headers": [(b"x-forwarded-for", v.encode()) for v in xff]}


@pytest.mark.parametrize("scope,esperado", [
    (_scope("127.0.0.1", "203.0.113.7"), "203.0.113.7"),
    (_scope("172.20.0.1", "203.0.113.7"), "203.0.113.7"),       # gateway do Docker, confiável
    (_scope("::1", "203.0.113.7"), "203.0.113.7"),
    (_scope("127.0.0.1", "1.1.1.1, 203.0.113.7"), "203.0.113.7"),  # o último é o do proxy
    (_scope("127.0.0.1", "1.1.1.1", "203.0.113.7"), "203.0.113.7"),
    (_scope("127.0.0.1", "lixo"), "127.0.0.1"),
    (_scope("127.0.0.1"), "127.0.0.1"),
    (_scope("198.51.100.9", "203.0.113.7"), "198.51.100.9"),   # quem não é proxy não escolhe o IP
    (_scope("127.0.0.1", "2001:db8:1:2:aaaa::1"), "2001:db8:1:2::/64"),
    (_scope("127.0.0.1", "::ffff:203.0.113.7"), "203.0.113.7"),
])
def test_ip_de_origem(scope, esperado):
    m = LimiteRequisicoes(None, limites={}, confiaveis=["127.0.0.0/8", "::1/128", "172.20.0.1"])
    assert m.ip_origem(scope) == esperado


def test_aviso_de_encaminhado_nao_confiavel_sem_inundar(caplog):
    agora = [1000.0]
    m = LimiteRequisicoes(None, limites={}, confiaveis=["127.0.0.1"], relogio=lambda: agora[0])
    with caplog.at_level(logging.WARNING, logger="assistente.limite"):
        for _ in range(5):
            assert m.ip_origem(_scope("198.51.100.9", "203.0.113.7")) == "198.51.100.9"
        m.ip_origem(_scope("198.51.100.9"))      # sem cabeçalho: nada a avisar
        m.ip_origem(_scope("127.0.0.1", "203.0.113.7"))  # proxy confiável: nada a avisar
        assert len([r for r in caplog.records if "X-Forwarded-For ignorado" in r.message]) == 1
        agora[0] += limite.AVISO_SEGUNDOS
        m.ip_origem(_scope("198.51.100.9", "203.0.113.7"))
        assert len([r for r in caplog.records if "X-Forwarded-For ignorado" in r.message]) == 2


def test_subida_loga_proxies_confiaveis(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="assistente.auth"):
        criar_app(_cfg(tmp_path, proxies_confiaveis="172.20.0.1,10.0.0.0/8"))
    assert any("proxies confiáveis" in r.message and "172.20.0.1, 10.0.0.0/8" in r.message for r in caplog.records)


async def test_janela_desliza_e_libera():
    agora = [1000.0]
    chamadas = []

    async def app(scope, receive, send):
        chamadas.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    m = LimiteRequisicoes(app, limites={"/register": 2}, confiaveis=["127.0.0.1"], janela=60, relogio=lambda: agora[0])

    async def status(path="/register"):
        enviados = []

        async def send(msg):
            enviados.append(msg)

        await m({"type": "http", "path": path, "client": ("127.0.0.1", 1), "headers": []}, None, send)
        return enviados[0]["status"]

    assert [await status(), await status(), await status()] == [200, 200, 429]
    assert await status("/token") == 200   # caminho sem limite
    assert await status("/register/") == 429  # barra no fim não escapa
    agora[0] += 61
    assert await status() == 200


def test_gateway_padrao(tmp_path):
    rotas = tmp_path / "route"
    rotas.write_text(
        "Iface\tDestination\tGateway \tFlags\n"
        "eth0\t00000000\t010014AC\t0003\n"
        "eth0\t000014AC\t00000000\t0001\n"
    )
    assert gateway_padrao(rotas) == "172.20.0.1"
    assert gateway_padrao(tmp_path / "nao-existe") is None


async def _registrar(c) -> str:
    r = await c.post("/register", json=REGISTRO)
    assert r.status_code == 201
    return r.json()["client_id"]


@pytest.mark.parametrize("dias", [None, 30])
async def test_cliente_sem_token_expira(tmp_path, dias):
    # O prazo some na troca do código por token: ver test_auth.py, test_troca_do_codigo_so_para_conta_permitida.
    servidor = criar_app(_cfg(tmp_path, **({"clientes_ttl_dias": dias} if dias else {})))
    auth = servidor.auth
    app = servidor.http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            cid = await _registrar(c)
    cliente, ttl = await auth._client_store.ttl(key=cid)
    assert cliente is not None
    segundos = (dias or 1) * 86400  # padrão: 1 dia
    assert segundos - 60 < ttl <= segundos


async def test_limpeza_apaga_do_disco_o_que_expirou(tmp_path):
    servidor = criar_app(_cfg(tmp_path))
    auth = servidor.auth
    await auth._client_store.put(key="velho", value=(await _cliente_salvo(servidor)), ttl=0.05)
    pasta = fastmcp.settings.home / "oauth-proxy"
    antes = {p.name for p in pasta.rglob("*") if p.is_file()}
    await asyncio.sleep(0.1)
    auth._ultima_limpeza = 0.0  # o /register acima já varreu
    await auth._limpar_expirados()
    depois = {p.name for p in pasta.rglob("*") if p.is_file()}
    assert len(depois) == len(antes) - 1
    assert (await auth._client_store.get(key="permanente")) is not None
    # Uma varredura por hora, no máximo.
    with patch.object(type(auth._client_storage.key_value), "cull") as cull:
        await auth._limpar_expirados()
    cull.assert_not_called()


async def _cliente_salvo(servidor):
    """Registra um cliente de verdade (sem prazo) e devolve o objeto para reaproveitar."""
    app = servidor.http_app()
    async with app.router.lifespan_context(app):
        async with _cliente(app) as c:
            cid = await _registrar(c)
    cliente = await servidor.auth._client_store.get(key=cid)
    await servidor.auth._client_store.put(key="permanente", value=cliente)
    return cliente
