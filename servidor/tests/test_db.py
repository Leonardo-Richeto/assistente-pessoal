"""Prazos da conexão com o banco."""

from assistente.db import PRAZO_COMANDO_MS, PRAZO_CONEXAO_S, opcoes_engine


def test_postgres_tem_prazo_de_conexao_e_de_comando():
    o = opcoes_engine("postgresql+psycopg://u:s@postgres/assistente")
    assert o["pool_timeout"] == PRAZO_CONEXAO_S
    assert o["connect_args"]["connect_timeout"] == PRAZO_CONEXAO_S
    assert f"statement_timeout={PRAZO_COMANDO_MS}" in o["connect_args"]["options"]


def test_sqlite_sem_opcoes_de_postgres():
    assert opcoes_engine("sqlite:///x.db") == {"pool_pre_ping": True}
