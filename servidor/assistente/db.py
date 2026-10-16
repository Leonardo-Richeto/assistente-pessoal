"""Duas conexões separadas: leitura (só SELECT) e escrita (só as ferramentas de registro)."""

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class Bancos:
    leitura: sessionmaker[Session]
    escrita: sessionmaker[Session]

    @classmethod
    def de_urls(cls, url_leitura: str, url_escrita: str) -> "Bancos":
        def fabrica(url: str) -> sessionmaker[Session]:
            engine = create_engine(url, pool_pre_ping=True)
            return sessionmaker(engine, expire_on_commit=False)

        return cls(leitura=fabrica(url_leitura), escrita=fabrica(url_escrita))
