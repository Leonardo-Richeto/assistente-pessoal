"""OAuth via GitHub, aceitando só os logins da lista.

O Claude (app/web) faz o fluxo OAuth com este servidor; o servidor delega o login ao GitHub
e, a cada requisição, confere se o usuário do GitHub está em GITHUB_LOGINS_PERMITIDOS.
Qualquer outra conta GitHub consegue logar no GitHub, mas recebe 401 aqui.
"""

import logging

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider

log = logging.getLogger(__name__)


class GitHubRestrito(GitHubProvider):
    def __init__(self, *, logins_permitidos: list[str], **kwargs):
        if not logins_permitidos:
            raise ValueError("GITHUB_LOGINS_PERMITIDOS está vazio: ninguém conseguiria entrar.")
        super().__init__(**kwargs)
        self._permitidos = {l.lower() for l in logins_permitidos}

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]
        acesso = await super().load_access_token(token)
        if acesso is None:
            return None
        login = str(acesso.claims.get("login") or "").lower()
        if login not in self._permitidos:
            log.warning("Acesso negado para o login GitHub %r", login)
            return None
        return acesso
