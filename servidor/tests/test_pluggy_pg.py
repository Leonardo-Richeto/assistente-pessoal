"""GRANTs de `sincronizacoes` e colunas novas de `gastos` no Postgres de verdade (Ficha 10; migração 0007).

Só roda com ASSISTENTE_PG_RASCUNHO = URL do DONO de um banco de RASCUNHO `teste_*` já migrado (alembic upgrade
head), com os papéis do deploy/postgres/01-papeis.sh. Sem a variável, o teste é pulado. Como subir o Postgres de
rascunho: test_desatualizadas_pg.py.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from assistente.modelos import Gasto, Sincronizacao
from test_concorrencia_pg import URL, url  # noqa: F401 (fixture: confere que é um banco teste_* migrado)
from test_desatualizadas_pg import ESCRITA, LEITURA, _como, _recusado

pytestmark = pytest.mark.skipif(not URL, reason="sem ASSISTENTE_PG_RASCUNHO (Postgres de rascunho)")


@pytest.fixture
def pg(url):  # noqa: F811
    engine = create_engine(url)
    try:
        with engine.connect() as cx:
            if cx.execute(text("SELECT to_regclass('sincronizacoes')")).scalar() is None:
                pytest.fail("Banco de rascunho sem a migração 0007: rode alembic upgrade head nele")
    finally:
        engine.dispose()
    return url


def test_privilegios_de_sincronizacoes(pg):
    engine = create_engine(pg)
    try:
        with engine.connect() as cx:
            def tem(papel: str, priv: str) -> bool:
                return cx.execute(text("SELECT has_table_privilege(:p, 'sincronizacoes', :priv)"),
                                  {"p": papel, "priv": priv}).scalar()

            privs = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            assert {p: tem(ESCRITA, p) for p in privs} == {
                "SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
            assert {p: tem(LEITURA, p) for p in privs} == {
                "SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
            assert cx.execute(text("SELECT has_table_privilege(:p, 'gastos', 'DELETE')"), {"p": ESCRITA}).scalar() is False
    finally:
        engine.dispose()


def test_escrita_grava_sincronizacao_e_gasto_conferido_mas_nao_apaga(pg):
    engine = _como(pg, ESCRITA)
    agora = datetime.now(timezone.utc)
    try:
        with Session(engine) as s, s.begin():
            s.add(Sincronizacao(worker="pluggy", inicio=agora, fim=agora, ok=True, novos=0))
            g = Gasto(data=date(2026, 10, 20), valor=Decimal("1.00"), descricao="teste 0007", categoria="outros",
                      origem="pluggy", conferido=False)
            s.add(g)
            s.flush()
            gid = g.id
        with Session(engine) as s, s.begin():
            s.get(Gasto, gid).conferido = True  # conferir_gastos: UPDATE em gastos
        with Session(engine) as s:
            assert s.get(Gasto, gid).conferido is True
        assert _recusado(engine, "UPDATE sincronizacoes SET ok = false")
        assert _recusado(engine, "DELETE FROM sincronizacoes")
    finally:
        engine.dispose()


def test_gasto_antigo_nasce_conferido(pg):
    engine = create_engine(pg)
    try:
        with engine.connect() as cx:
            padrao = cx.execute(text("SELECT column_default FROM information_schema.columns "
                                     "WHERE table_name = 'gastos' AND column_name = 'conferido'")).scalar()
        assert padrao == "true"
    finally:
        engine.dispose()
