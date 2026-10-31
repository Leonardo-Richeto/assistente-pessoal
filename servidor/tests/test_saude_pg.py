"""GRANTs das tabelas de saúde e a importação pelo usuário de escrita, no Postgres de verdade (Ficha 14; migração 0008).

Só roda com ASSISTENTE_PG_RASCUNHO = URL do DONO de um banco de RASCUNHO `teste_*` já migrado (alembic upgrade
head). Como subir o Postgres de rascunho: test_desatualizadas_pg.py. O export é o sintético de test_saude.py.
"""

import pytest
from sqlalchemy import create_engine, text

from assistente import saude
from test_concorrencia_pg import URL, url  # noqa: F401 (fixture: confere que é um banco teste_* migrado)
from test_desatualizadas_pg import ESCRITA, LEITURA, _como, _recusado
from test_saude import FC_REPETIDA, montar, xml

TABELAS = ("saude_importacoes", "saude_amostras", "saude_treinos", "saude_rotas", "saude_aneis", "saude_ecg")
TODOS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

pytestmark = pytest.mark.skipif(not URL, reason="sem ASSISTENTE_PG_RASCUNHO (Postgres de rascunho)")


@pytest.fixture
def pg(url):  # noqa: F811
    engine = create_engine(url)
    try:
        with engine.connect() as cx:
            if cx.execute(text("SELECT to_regclass('saude_amostras')")).scalar() is None:
                pytest.fail("Banco de rascunho sem a migração 0008: rode alembic upgrade head nele")
    finally:
        engine.dispose()
    return url


def test_privilegios_pelo_catalogo(pg):
    engine = create_engine(pg)
    try:
        with engine.connect() as cx:
            def tem(sql: str, **args) -> bool:
                return cx.execute(text(sql), args).scalar()

            for tabela in TABELAS:
                priv_tabela = f"SELECT has_table_privilege(:p, '{tabela}', :priv)"
                assert {p: tem(priv_tabela, p=ESCRITA, priv=p) for p in TODOS} == {
                    **dict.fromkeys(TODOS, False), "SELECT": True, "INSERT": True}, tabela
                assert {p: tem(priv_tabela, p=LEITURA, priv=p) for p in TODOS} == {
                    **dict.fromkeys(TODOS, False), "SELECT": True}, tabela
                seq = f"SELECT has_sequence_privilege(:p, '{tabela}_id_seq', 'USAGE')"
                assert tem(seq, p=ESCRITA) and not tem(seq, p=LEITURA), tabela
            # UPDATE de coluna: só as de resultado da importação, só para a escrita (migração 0008).
            assert set(cx.execute(text(
                "SELECT grantee, table_name, column_name FROM information_schema.column_privileges "
                "WHERE table_name LIKE 'saude\\_%' AND privilege_type = 'UPDATE' AND grantee IN (:e, :l)"),
                {"e": ESCRITA, "l": LEITURA}).all()) == {
                (ESCRITA, "saude_importacoes", c) for c in ("fim", "ok", "data_export", "perfil", "contagens")}
    finally:
        engine.dispose()


def test_importa_pela_escrita_e_nao_muda_nem_apaga(pg, tmp_path):
    escrita, leitura, dono = _como(pg, ESCRITA), _como(pg, LEITURA), create_engine(pg)
    try:
        with dono.connect() as cx:
            antes = cx.execute(text("SELECT count(*) FROM saude_amostras")).scalar()
        r = saude.importar(montar(tmp_path), escrita)
        novos = r["tabelas"]["saude_amostras"]["novos"]
        # O banco de rascunho pode já ter o export sintético de uma rodada anterior: aí tudo é repetido.
        assert novos + r["tabelas"]["saude_amostras"]["repetidos"] == 4
        de_novo = saude.importar(montar(tmp_path, nome="b.zip"), escrita)
        # A mesma amostra duas vezes no mesmo arquivo (no mesmo lote): uma entra, a outra conta como repetida.
        dupla = saude.importar(montar(tmp_path, nome="c.zip", conteudo_xml=xml(amostras=FC_REPETIDA)), escrita)
        assert dupla["tabelas"]["saude_amostras"] == {"novos": 0, "repetidos": 5}
        assert all(c["novos"] == 0 for c in de_novo["tabelas"].values())
        with dono.connect() as cx:
            assert cx.execute(text("SELECT count(*) FROM saude_amostras")).scalar() == antes + novos
            alvo = {"id": cx.execute(text("SELECT max(id) FROM saude_amostras")).scalar()}
        assert _recusado(escrita, "UPDATE saude_amostras SET valor = 0 WHERE id = :id", **alvo)
        assert _recusado(escrita, "UPDATE saude_amostras SET desfeito = true WHERE id = :id", **alvo)
        assert _recusado(escrita, "DELETE FROM saude_amostras WHERE id = :id", **alvo)
        assert _recusado(escrita, "TRUNCATE saude_rotas")
        assert _recusado(escrita, "UPDATE saude_importacoes SET arquivo = 'outro' WHERE id = 1")
        assert _recusado(escrita, "DELETE FROM saude_importacoes WHERE id = 1")
        assert not _recusado(leitura, "SELECT valor FROM saude_amostras WHERE id = :id", **alvo)
        assert _recusado(leitura, "DELETE FROM saude_amostras WHERE id = :id", **alvo)
    finally:
        for engine in (escrita, leitura, dono):
            engine.dispose()
