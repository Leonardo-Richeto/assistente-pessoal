"""Duas conexões separadas: leitura (só SELECT) e escrita (só as ferramentas de registro)."""

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Prazo curto para conectar e para cada comando: com o Postgres travado, a chamada falha rápido em vez
# de prender as threads do servidor (o registro de chamadas roda em toda leitura).
PRAZO_CONEXAO_S = 3
PRAZO_COMANDO_MS = 5000


def opcoes_engine(url: str) -> dict:
    """Opções do create_engine; os prazos só valem para Postgres (os testes usam SQLite)."""
    opcoes: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        opcoes["pool_timeout"] = PRAZO_CONEXAO_S
        opcoes["connect_args"] = {
            "connect_timeout": PRAZO_CONEXAO_S,
            "options": f"-c statement_timeout={PRAZO_COMANDO_MS}",
        }
    return opcoes


@dataclass
class Bancos:
    leitura: sessionmaker[Session]
    escrita: sessionmaker[Session]

    @classmethod
    def de_urls(cls, url_leitura: str, url_escrita: str) -> "Bancos":
        def fabrica(url: str) -> sessionmaker[Session]:
            engine = create_engine(url, **opcoes_engine(url))
            return sessionmaker(engine, expire_on_commit=False)

        return cls(leitura=fabrica(url_leitura), escrita=fabrica(url_escrita))
