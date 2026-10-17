"""Configuração lida do ambiente (.env)."""

import ipaddress
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Callback do claude.ai (web, desktop e celular). A documentação da Anthropic avisa que pode
# passar a claude.com; as duas ficam liberadas.
REDIRECTS_CLAUDE = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco: dois usuários. Leitura só tem SELECT; escrita só INSERT/UPDATE nas tabelas de domínio.
    database_url_leitura: str
    database_url_escrita: str

    # Endereço público (o do Tailscale Funnel), ex.: https://maquina.tailnet.ts.net
    public_base_url: str = "http://localhost:8000"
    porta: int = 8000

    # Login: "github" ou "google". Só as identidades listadas entram.
    auth_provedor: Literal["github", "google"] = "github"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_logins_permitidos: Annotated[list[str], NoDecode] = Field(default_factory=list)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_emails_permitidos: Annotated[list[str], NoDecode] = Field(default_factory=list)
    jwt_signing_key: str = ""
    # Para onde o login pode devolver o cliente MCP (registro dinâmico). O claude.ai sempre entra;
    # a variável só soma. Sem esta lista, o FastMCP aceita qualquer https.
    auth_redirects_permitidos: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(REDIRECTS_CLAUDE))
    # Limite por IP de origem, por hora, nos endpoints públicos do login. /consent usa o do
    # /authorize; o callback do login usa o do /token.
    limite_register_por_hora: int = Field(10, ge=1)
    limite_authorize_por_hora: int = Field(30, ge=1)
    limite_token_por_hora: int = Field(60, ge=1)
    # Teto por hora somando todos os IPs (segura quem troca de IP). /consent usa o do /authorize.
    limite_global_register_por_hora: int = Field(100, ge=1)
    limite_global_authorize_por_hora: int = Field(300, ge=1)
    # De quem aceitar X-Forwarded-For (IPs ou redes). Vazio = loopback e o gateway do container
    # (no Docker, a conexão do Tailscale chega pelo gateway da rede, não por 127.0.0.1).
    proxies_confiaveis: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Cliente registrado que nunca trocou código por token some depois disto. O claude.ai troca na
    # hora; 1 dia sobra.
    clientes_ttl_dias: int = Field(1, ge=1)

    # Quem é o dono desta instância (vai nas instruções que o modelo recebe).
    nome_usuario: str = "Leonardo"

    # Só para testes locais, nunca com o tunnel ligado.
    auth_desativada: bool = False

    # Peças prontas (opcionais). Vazio = não monta.
    paperless_url: str = ""
    paperless_api_key: str = ""
    vault_path: str = ""

    fuso: str = "America/Sao_Paulo"

    @field_validator("github_logins_permitidos", "google_emails_permitidos", mode="before")
    @classmethod
    def _separar_logins(cls, v):
        if isinstance(v, str):
            return [x.strip().lower() for x in v.split(",") if x.strip()]
        return [x.lower() for x in v]

    @field_validator("auth_redirects_permitidos", mode="before")
    @classmethod
    def _separar_redirects(cls, v):
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        for padrao in v:
            u = urlparse(padrao)
            # No FastMCP, padrão sem caminho (ou só "/" e "*") aceita qualquer caminho do host.
            if u.scheme != "https" or not u.hostname or not u.path.strip("/*"):
                raise ValueError(f"AUTH_REDIRECTS_PERMITIDOS: {padrao!r} precisa de https, host e caminho "
                                 "(ex.: https://exemplo.com/callback); sem caminho vale para o host inteiro.")
            # O FastMCP compara o caminho com fnmatch ("?" e "[...]" são curingas) e ignora a query.
            if "?" in padrao or "#" in padrao or "[" in u.path or "]" in u.path:
                raise ValueError(f"AUTH_REDIRECTS_PERMITIDOS: {padrao!r} não pode ter '?', '#', '[' ou ']'.")
        return list(dict.fromkeys([*REDIRECTS_CLAUDE, *v]))

    @field_validator("proxies_confiaveis", mode="before")
    @classmethod
    def _separar_proxies(cls, v):
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        for rede in v:
            ipaddress.ip_network(rede, strict=False)  # ValueError com o valor errado
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)


@lru_cache
def config() -> Config:
    return Config()
