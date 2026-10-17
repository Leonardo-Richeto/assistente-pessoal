"""vincular_nota sob concorrência no Postgres de verdade (Passo 8e; pendência do revisor do 8c).

Só roda com ASSISTENTE_PG_RASCUNHO = URL de um banco de RASCUNHO já migrado (alembic upgrade head), com nome
começando por `teste_`. Sem a variável, o teste é pulado. O SQLite dos outros testes não tem `FOR UPDATE`.

Como rodar, da raiz do projeto, com a stack no ar (a senha vem do compose; ninguém lê o .env):
    docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" teste_pg'
    docker compose run --rm --no-deps --user root -v "$PWD/servidor/tests:/app/tests:ro" \\
      -v "$PWD/servidor/assistente:/app/assistente:ro" -v "$PWD/servidor/alembic:/app/alembic:ro" migracao sh -c \\
      'set -e; export DATABASE_URL_MIGRACAO="${DATABASE_URL_MIGRACAO%/assistente}/teste_pg";
       export ASSISTENTE_PG_RASCUNHO="$DATABASE_URL_MIGRACAO"; alembic upgrade head; uv sync --frozen -q;
       python -m pytest -q -p no:cacheprovider tests/test_concorrencia_pg.py'
    docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" teste_pg'

O teste grava gastos e linhas de auditoria no banco de rascunho; nunca aponte para o banco real.
"""

import os
import threading
import time
from decimal import Decimal
from zoneinfo import ZoneInfo

import anyio
import pytest
from sqlalchemy import create_engine, inspect, make_url, select, text
from sqlalchemy.orm import Session

from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from assistente.modelos import Auditoria, Gasto

URL = os.environ.get("ASSISTENTE_PG_RASCUNHO", "")
PREFIXO_RASCUNHO = "teste_"
TZ = ZoneInfo("America/Sao_Paulo")

pytestmark = pytest.mark.skipif(not URL, reason="sem ASSISTENTE_PG_RASCUNHO (Postgres de rascunho)")


@pytest.fixture
def url():
    destino = make_url(URL)
    if not destino.drivername.startswith("postgresql"):
        pytest.fail("ASSISTENTE_PG_RASCUNHO precisa ser um Postgres")
    if not (destino.database or "").startswith(PREFIXO_RASCUNHO):
        pytest.fail(f"ASSISTENTE_PG_RASCUNHO precisa apontar para um banco '{PREFIXO_RASCUNHO}*', nunca o real")
    engine = create_engine(URL)
    try:
        # O nome que vale é o do banco conectado: parâmetros da query (dbname=...) passam por cima do caminho da URL.
        with engine.connect() as cx:
            conectado = cx.execute(text("SELECT current_database()")).scalar()
        if not conectado.startswith(PREFIXO_RASCUNHO):
            pytest.fail(f"ASSISTENTE_PG_RASCUNHO conectou em '{conectado}', não num banco '{PREFIXO_RASCUNHO}*'")
        if "nota_vault" not in {c["name"] for c in inspect(engine).get_columns("gastos")}:
            pytest.fail("Banco de rascunho sem a migração 0004: rode alembic upgrade head nele")
    finally:
        engine.dispose()
    return URL


def _ferramentas(url):
    """As funções das ferramentas, chamadas direto (sem o schema: argumentos já no tipo certo) em threads."""
    bancos = Bancos.de_urls(url, url)
    mcp = criar_servidor_banco(bancos, TZ)
    return bancos, anyio.run(mcp.get_tool, "registrar_gasto").fn, anyio.run(mcp.get_tool, "vincular_nota").fn


def _esperando_trava(engine, quantos: int, prazo_s: float = 3.0) -> int:
    """Quantas conexões deste banco estão paradas esperando trava de linha (espera até `quantos` ou o prazo)."""
    fim = time.monotonic() + prazo_s
    while True:
        with engine.connect() as cx:
            n = cx.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                "AND wait_event_type = 'Lock'")).scalar()
        if n >= quantos or time.monotonic() > fim:
            return n
        time.sleep(0.05)


def test_duas_trocas_simultaneas_encadeiam_o_anterior(url):
    bancos, registrar_gasto, vincular_nota = _ferramentas(url)
    engine = create_engine(url)
    try:
        _trocas_simultaneas(engine, registrar_gasto, vincular_nota)
    finally:
        engine.dispose()
        bancos.leitura.kw["bind"].dispose()
        bancos.escrita.kw["bind"].dispose()


def _trocas_simultaneas(engine, registrar_gasto, vincular_nota):
    gid = registrar_gasto(valor=Decimal("1.00"), descricao="teste 8e", categoria="teste", nota_vault="00-inbox/a0.md")["id"]
    resultados, erros = {}, []

    def trocar(caminho):
        try:
            resultados[caminho] = vincular_nota(tipo="gasto", id=gid, caminho=caminho)
        except Exception as e:  # noqa: BLE001 (o teste mostra o erro)
            erros.append(e)

    # Uma terceira conexão segura a linha do gasto: as duas trocas começam e param juntas na trava. Ao soltar,
    # as duas disputam a linha ao mesmo tempo. Sem FOR UPDATE, as duas leriam "a0" como anterior.
    with Session(engine) as trava, trava.begin():
        trava.execute(select(Gasto).where(Gasto.id == gid).with_for_update())
        threads = [threading.Thread(target=trocar, args=(c,)) for c in ("00-inbox/a1.md", "00-inbox/a2.md")]
        for t in threads:
            t.start()
        paradas = _esperando_trava(engine, 2)
    for t in threads:
        t.join(timeout=10)

    assert not erros, erros
    assert paradas == 2, "as duas trocas deveriam esperar a trava ao mesmo tempo"
    with Session(engine) as s:
        linhas = s.scalars(select(Auditoria).where(Auditoria.tabela == "gastos", Auditoria.registro_id == gid,
                                                   Auditoria.acao == "vincular").order_by(Auditoria.id)).all()
        final = s.get(Gasto, gid).nota_vault

    assert len(linhas) == 2
    primeira, segunda = linhas
    assert primeira.dados["anterior"] == "00-inbox/a0.md"
    assert segunda.dados["anterior"] == primeira.dados["caminho"]  # encadeado: ninguém perdeu o anterior
    assert {primeira.dados["caminho"], segunda.dados["caminho"]} == {"00-inbox/a1.md", "00-inbox/a2.md"}
    assert final == segunda.dados["caminho"]
    assert sorted(r["vinculo"] for r in resultados.values()) == [primeira.id, segunda.id]
