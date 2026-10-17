"""Login via GitHub ou Google, aceitando só as identidades da lista.

O Claude (ou outro cliente MCP) faz o fluxo OAuth com este servidor; o servidor delega o
login ao provedor escolhido em AUTH_PROVEDOR e, a cada requisição, confere a identidade:
- github: o login do GitHub precisa estar em GITHUB_LOGINS_PERMITIDOS
- google: o e-mail (verificado) precisa estar em GOOGLE_EMAILS_PERMITIDOS
Qualquer outra conta consegue logar no provedor, mas recebe 401 aqui.
"""

import logging

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.google import GoogleProvider

log = logging.getLogger(__name__)


class _Restrito:
    """Mixin: aplica a lista de permitidos depois da validação normal do provedor."""

    def _iniciar_lista(self, permitidos: list[str], nome_var: str) -> None:
        if not permitidos:
            raise ValueError(f"{nome_var} está vazio: ninguém conseguiria entrar.")
        self._permitidos = {p.strip().lower() for p in permitidos}

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
        super().__init__(**kwargs)

    def _identidade(self, acesso):
        return acesso.claims.get("login")


class GoogleRestrito(_Restrito, GoogleProvider):
    def __init__(self, *, emails_permitidos: list[str], **kwargs):
        self._iniciar_lista(emails_permitidos, "GOOGLE_EMAILS_PERMITIDOS")
        super().__init__(required_scopes=["openid", "email"], **kwargs)

    def _identidade(self, acesso):
        # Falha fechado: só vale e-mail com email_verified verdadeiro. O tokeninfo do Google manda
        # texto ("true"/"false"); o userinfo manda booleano. Claim ausente = recusa.
        if str(acesso.claims.get("email_verified")).strip().lower() != "true":
            return None
        return acesso.claims.get("email")
