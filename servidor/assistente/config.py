"""Configuração lida do ambiente (.env)."""

from functools import lru_cache
from typing import Annotated, Literal
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
    # Para onde o login pode devolver o cliente MCP (registro dinâmico). Vazio = só o claude.ai.
    # Sem esta lista, o FastMCP aceita qualquer https.
    auth_redirects_permitidos: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(REDIRECTS_CLAUDE))

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
        return v or list(REDIRECTS_CLAUDE)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)


@lru_cache
def config() -> Config:
    return Config()
