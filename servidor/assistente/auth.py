"""Login via GitHub ou Google, aceitando só as identidades da lista.

O Claude (ou outro cliente MCP) faz o fluxo OAuth com este servidor; o servidor delega o
login ao provedor escolhido em AUTH_PROVEDOR e, a cada requisição, confere a identidade:
- github: o login do GitHub precisa estar em GITHUB_LOGINS_PERMITIDOS
- google: o e-mail (verificado) precisa estar em GOOGLE_EMAILS_PERMITIDOS
Qualquer outra conta consegue logar no provedor, mas a troca do código por token falha aqui
(invalid_grant) e, se um token antigo existir, ele recebe 401.

Também: limites por IP e globais nos endpoints públicos do login (assistente/limite.py) e prazo
para cliente registrado que nunca pegou token (some do volume oauth).
"""

import logging
import time

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.google import GoogleProvider
from mcp.server.auth.provider import TokenError
from starlette.middleware import Middleware

from .limite import LimiteRequisicoes, proxies_padrao

log = logging.getLogger(__name__)

LIMPEZA_SEGUNDOS = 3600  # no máximo uma varredura de expirados por hora
# Parâmetros de limite e prazo aceitos pelos provedores (ver _iniciar_limites).
OPCOES_LIMITE = ("limite_register", "limite_authorize", "limite_token", "limite_global_register",
                 "limite_global_authorize", "proxies_confiaveis", "clientes_ttl_dias")


class _Restrito:
    """Mixin: aplica a lista de permitidos depois da validação normal do provedor."""

    def _iniciar_lista(self, permitidos: list[str], nome_var: str) -> None:
        if not permitidos:
            raise ValueError(f"{nome_var} está vazio: ninguém conseguiria entrar.")
        self._permitidos = {p.strip().lower() for p in permitidos}

    def _iniciar_limites(self, *, limite_register: int = 10, limite_authorize: int = 30, limite_token: int = 60,
                         limite_global_register: int = 100, limite_global_authorize: int = 300,
                         proxies_confiaveis: list[str] | None = None, clientes_ttl_dias: int = 1) -> None:
        self._limite_por_ip = (limite_register, limite_authorize, limite_token)
        self._limite_global = (limite_global_register, limite_global_authorize)
        self._proxies_confiaveis = proxies_confiaveis or proxies_padrao()
        self._ttl_clientes = clientes_ttl_dias * 86400
        self._ultima_limpeza = 0.0
        log.info("Login: proxies confiáveis para X-Forwarded-For: %s", ", ".join(self._proxies_confiaveis))

    def _limites(self) -> tuple[dict[str, int], dict[str, int]]:
        """Limites por hora: (por IP, globais). /consent grava o CSRF a cada exibição; vale o do /authorize."""
        register, authorize, token = self._limite_por_ip
        global_register, global_authorize = self._limite_global
        callback = self._redirect_path  # type: ignore[attr-defined]
        por_ip = {"/register": register, "/authorize": authorize, "/consent": authorize,
                  "/token": token, callback: token}
        # /token e o callback só gravam com código ou login válidos; sem teto global, ninguém trava o refresh.
        globais = {"/register": global_register, "/authorize": global_authorize, "/consent": global_authorize}
        return por_ip, globais

    def get_middleware(self) -> list:
        # Primeiro da lista = roda antes de tudo, inclusive da leitura do token.
        por_ip, globais = self._limites()
        limite = Middleware(LimiteRequisicoes, limites=por_ip, globais=globais, confiaveis=self._proxies_confiaveis)
        return [limite, *super().get_middleware()]  # type: ignore[misc]

    async def _guardar_cliente(self, client_id: str, ttl: float | None) -> None:
        """Regrava o cliente com outro prazo (None = sem prazo). Usa o store interno do OAuthProxy."""
        cliente = await self._client_store.get(key=client_id)  # type: ignore[attr-defined]
        if cliente is not None:
            await self._client_store.put(key=client_id, value=cliente, ttl=ttl)  # type: ignore[attr-defined]

    async def _limpar_expirados(self) -> None:
        """Apaga do disco o que já expirou. O FileTreeStore só esconde expirado; não apaga sozinho."""
        agora = time.monotonic()
        if self._ultima_limpeza and agora - self._ultima_limpeza < LIMPEZA_SEGUNDOS:
            return
        self._ultima_limpeza = agora
        cull = getattr(getattr(self._client_storage, "key_value", None), "cull", None)  # type: ignore[attr-defined]
        if cull is None:
            return
        try:
            await cull()
        except Exception:
            log.exception("Falha ao limpar expirados do volume oauth")

    async def register_client(self, client_info) -> None:  # type: ignore[override]
        await self._limpar_expirados()
        await super().register_client(client_info)  # type: ignore[misc]
        await self._guardar_cliente(client_info.client_id, self._ttl_clientes)

    async def authorize(self, client, params) -> str:  # type: ignore[override]
        await self._limpar_expirados()
        return await super().authorize(client, params)  # type: ignore[misc]

    async def _conferir_conta_do_codigo(self, codigo: str) -> None:
        """Antes de emitir token: a conta que logou no provedor precisa estar na lista. Falha fechado.

        O FastMCP 4.1.0 não confere a lista na troca do código (oauth_proxy/proxy.py,
        exchange_authorization_code); sem isto, qualquer conta recebe token (e o cliente perde o prazo).
        """
        modelo = await self._code_store.get(key=codigo)  # type: ignore[attr-defined]
        if modelo is None:
            return  # o FastMCP responde invalid_grant
        token_provedor = (modelo.idp_tokens or {}).get("access_token")
        acesso = None
        if token_provedor:
            try:
                acesso = await self._token_validator.verify_token(token_provedor)  # type: ignore[attr-defined]
            except Exception:
                log.exception("Falha ao validar no provedor o token do código")
        ident = (self._identidade(acesso) or "").lower() if acesso is not None else ""
        if ident not in self._permitidos:
            await self._code_store.delete(key=codigo)  # type: ignore[attr-defined]
            log.warning("Troca de código negada para %r", ident)
            raise TokenError("invalid_grant", "Conta não permitida neste servidor.")

    async def exchange_authorization_code(self, client, authorization_code):  # type: ignore[override]
        await self._conferir_conta_do_codigo(authorization_code.code)
        tokens = await super().exchange_authorization_code(client, authorization_code)  # type: ignore[misc]
        # Cliente em uso não expira: o refresh precisa dele.
        await self._guardar_cliente(client.client_id, None)
        return tokens

    def _identidade(self, acesso: AccessToken) -> str | None:
        raise NotImplementedError

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]
        acesso = await super().load_access_token(token)  # type: ignore[misc]
        if acesso is None:
            return None
        ident = (self._identidade(acesso) or "").lower()
        if ident not in self._permitidos:
            log.warning("Acesso negado para %r", ident)
            return None
        return acesso


class GitHubRestrito(_Restrito, GitHubProvider):
    def __init__(self, *, logins_permitidos: list[str], **kwargs):
        self._iniciar_lista(logins_permitidos, "GITHUB_LOGINS_PERMITIDOS")
        self._iniciar_limites(**{k: kwargs.pop(k) for k in OPCOES_LIMITE if k in kwargs})
        super().__init__(**kwargs)

    def _identidade(self, acesso):
        return acesso.claims.get("login")


class GoogleRestrito(_Restrito, GoogleProvider):
    def __init__(self, *, emails_permitidos: list[str], **kwargs):
        self._iniciar_lista(emails_permitidos, "GOOGLE_EMAILS_PERMITIDOS")
        self._iniciar_limites(**{k: kwargs.pop(k) for k in OPCOES_LIMITE if k in kwargs})
        super().__init__(required_scopes=["openid", "email"], **kwargs)

    def _identidade(self, acesso):
        # Falha fechado: só vale e-mail com email_verified verdadeiro. O tokeninfo do Google manda
        # texto ("true"/"false"); o userinfo manda booleano. Claim ausente = recusa.
        if str(acesso.claims.get("email_verified")).strip().lower() != "true":
            return None
        return acesso.claims.get("email")
