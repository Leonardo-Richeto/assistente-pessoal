"""Limite de requisições nos endpoints públicos do login: por IP de origem e um teto global.

`/register`, `/authorize` e `/consent` respondem sem token e gravam no volume oauth; sem limite,
qualquer um enche o disco. O teto global por caminho segura quem troca de IP (um /48 de IPv6 tem
65 mil blocos /64). Contagem em memória, janela deslizante de uma hora. Reiniciar zera a contagem.

IP de origem: atrás do Tailscale Funnel (ou Serve), a conexão chega do proxy local e o IP real
vem em `X-Forwarded-For`. O Tailscale troca o cabeçalho inteiro pelo IP do cliente
(`ipn/ipnlocal/serve.go`, `addProxyForwardedHeaders`, `Header.Set`), então o valor do cliente não
passa. Só confiamos no cabeçalho quando a conexão vem de um proxy confiável.
"""

import ipaddress
import logging
import math
import time
from collections import deque
from pathlib import Path

from starlette.responses import JSONResponse

log = logging.getLogger(__name__)

JANELA_SEGUNDOS = 3600
MAX_CHAVES = 10_000  # teto de IPs lembrados; acima disso, esquece os mais antigos
AVISO_SEGUNDOS = 600  # cada tipo de aviso sai no máximo uma vez a cada 10 minutos (não inunda o log)
LOOPBACK = ["127.0.0.0/8", "::1/128"]


def gateway_padrao(rotas: Path = Path("/proc/net/route")) -> str | None:
    """Gateway padrão do container (no Docker, é o host). None fora do Linux."""
    try:
        linhas = rotas.read_text().splitlines()[1:]
    except OSError:
        return None
    for linha in linhas:
        campos = linha.split()
        if len(campos) > 2 and campos[1] == "00000000":
            return str(ipaddress.IPv4Address(int(campos[2], 16).to_bytes(4, "little")))
    return None


def proxies_padrao() -> list[str]:
    gw = gateway_padrao()
    return LOOPBACK + ([gw] if gw else [])


def _chave_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    # IPv6: a mesma pessoa troca de endereço dentro do /64; conta o bloco inteiro.
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class LimiteRequisicoes:
    """Middleware ASGI: 429 quando um IP, ou todos somados, passam do limite por hora num caminho."""

    def __init__(self, app, *, limites: dict[str, int], confiaveis: list[str], globais: dict[str, int] | None = None,
                 janela: float = JANELA_SEGUNDOS, relogio=time.monotonic):
        self.app = app
        self.limites = limites
        self.globais = globais or {}
        self.confiaveis = [ipaddress.ip_network(c, strict=False) for c in confiaveis]
        self.janela = janela
        self.relogio = relogio
        self.vistos: dict[tuple[str, str], deque[float]] = {}
        self.vistos_globais: dict[str, deque[float]] = {}
        self._avisos: dict[tuple[str, str], float] = {}

    def _avisar(self, chave: tuple[str, str], msg: str, *args) -> None:
        """Log de aviso com limite de frequência por tipo e caminho."""
        agora = self.relogio()
        ultimo = self._avisos.get(chave)
        if ultimo is None or agora - ultimo >= AVISO_SEGUNDOS:
            self._avisos[chave] = agora
            log.warning(msg, *args)

    def ip_origem(self, scope) -> str:
        par = (scope.get("client") or ("",))[0]
        try:
            ip = ipaddress.ip_address(par)
        except ValueError:
            return par or "desconhecido"
        encaminhados = [v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-forwarded-for"]
        if not encaminhados:
            return _chave_ip(ip)
        if not any(ip in rede for rede in self.confiaveis):
            self._avisar(("xff", ""), "X-Forwarded-For ignorado: veio de %s, que não está nos proxies confiáveis", par)
            return _chave_ip(ip)
        # O último valor é o que o proxy confiável acrescentou.
        try:
            ip = ipaddress.ip_address(encaminhados[-1].split(",")[-1].strip())
        except ValueError:
            pass
        return _chave_ip(ip)

    def _limpar(self, fila: deque[float], agora: float) -> deque[float]:
        while fila and fila[0] <= agora - self.janela:
            fila.popleft()
        return fila

    def _fila(self, chave: tuple[str, str], agora: float) -> deque[float]:
        fila = self._limpar(self.vistos.pop(chave, None) or deque(), agora)
        if len(self.vistos) >= MAX_CHAVES:
            for velha in [k for k, f in self.vistos.items() if not f or f[-1] <= agora - self.janela]:
                del self.vistos[velha]
            while len(self.vistos) >= MAX_CHAVES:
                del self.vistos[next(iter(self.vistos))]
        self.vistos[chave] = fila  # reinsere no fim: ordem = uso mais recente
        return fila

    def _recusar(self, fila: deque[float], agora: float, limite: int):
        espera = max(1, math.ceil(fila[0] + self.janela - agora))
        return JSONResponse(
            {"error": "too_many_requests", "error_description": f"Limite de {limite} por hora. Tente mais tarde."},
            status_code=429, headers={"Retry-After": str(espera)},
        )

    async def __call__(self, scope, receive, send):
        caminho = (scope.get("path") or "").rstrip("/") or "/"
        limite = self.limites.get(caminho) if scope["type"] == "http" else None
        teto = self.globais.get(caminho) if scope["type"] == "http" else None
        if limite is None and teto is None:
            return await self.app(scope, receive, send)
        ip = self.ip_origem(scope)
        agora = self.relogio()
        fila = self._fila((caminho, ip), agora)
        if limite is not None and len(fila) >= limite:
            self._avisar(("ip", caminho), "Limite de %s atingido para %s (%d por hora)", caminho, ip, limite)
            return await self._recusar(fila, agora, limite)(scope, receive, send)
        geral = self._limpar(self.vistos_globais.setdefault(caminho, deque()), agora) if teto is not None else None
        if geral is not None and len(geral) >= teto:
            self._avisar(("global", caminho), "Teto global de %s atingido (%d por hora); último IP %s", caminho, teto, ip)
            return await self._recusar(geral, agora, teto)(scope, receive, send)
        fila.append(agora)
        if geral is not None:
            geral.append(agora)
        log.info("%s de %s (%d/%s na última hora; %s/%s no total)", caminho, ip, len(fila), limite or "-",
                 len(geral) if geral is not None else "-", teto or "-")
        await self.app(scope, receive, send)
