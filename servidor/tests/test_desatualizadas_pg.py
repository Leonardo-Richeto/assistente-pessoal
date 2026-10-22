"""GRANTs de `notas_desatualizadas` no Postgres de verdade (Sprint 2b, Passo 8; migração 0005).

Só roda com ASSISTENTE_PG_RASCUNHO = URL do DONO de um banco de RASCUNHO `teste_*` já migrado (alembic upgrade
head), com os papéis do deploy/postgres/01-papeis.sh. Sem a variável, o teste é pulado. A URL é a mesma de
test_concorrencia_pg.py. O dono (POSTGRES_USER, superusuário) troca de papel com SET ROLE: o Postgres confere os
privilégios do papel em vigor, como numa conexão com o usuário de leitura ou de escrita.

Como rodar no Mac, sem tocar na stack (container descartável, papéis criados pelo próprio 01-papeis.sh):
    docker run --rm -d --name pg-rascunho-8 -e POSTGRES_PASSWORD=x -e POSTGRES_USER=assistente_dono \\
      -e POSTGRES_DB=teste_pg -e SENHA_LEITURA=l -e SENHA_ESCRITA=e \\
      -v "$PWD/deploy/postgres/01-papeis.sh:/docker-entrypoint-initdb.d/01-papeis.sh:ro" \\
      -p 127.0.0.1:55438:5432 postgres:16.15
    cd servidor && export ASSISTENTE_PG_RASCUNHO=postgresql+psycopg://assistente_dono:x@127.0.0.1:55438/teste_pg
    DATABASE_URL_MIGRACAO="$ASSISTENTE_PG_RASCUNHO" PYTHONPATH=. uv run alembic upgrade head
    PYTHONPATH=. uv run pytest -q tests/test_desatualizadas_pg.py tests/test_concorrencia_pg.py
    docker stop pg-rascunho-8
"""

import uuid
from zoneinfo import ZoneInfo

import anyio
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from test_concorrencia_pg import URL, url  # noqa: F401 (fixture: confere que é um banco teste_* migrado)

TZ = ZoneInfo("America/Sao_Paulo")
TABELA = "notas_desatualizadas"
ESCRITA, LEITURA = "assistente_escrita", "assistente_leitura"

pytestmark = pytest.mark.skipif(not URL, reason="sem ASSISTENTE_PG_RASCUNHO (Postgres de rascunho)")


@pytest.fixture
def pg(url):  # noqa: F811
    engine = create_engine(url)
    try:
        with engine.connect() as cx:
            papeis = cx.execute(text("SELECT count(*) FROM pg_roles WHERE rolname IN (:e, :l)"),
                                {"e": ESCRITA, "l": LEITURA}).scalar()
            if papeis != 2:
                pytest.fail("Banco de rascunho sem os papéis do 01-papeis.sh")
            if cx.execute(text("SELECT to_regclass(:t)"), {"t": TABELA}).scalar() is None:
                pytest.fail("Banco de rascunho sem a migração 0005: rode alembic upgrade head nele")
    finally:
        engine.dispose()
    return url


def _como(url: str, papel: str):
    """Engine cujas conexões rodam com o papel dado (SET ROLE logo ao conectar)."""
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _papel(conexao, _registro):
        with conexao.cursor() as cur:
            cur.execute(f"SET ROLE {papel}")
        conexao.commit()

    return engine


def test_privilegios_pelo_catalogo(pg):
    engine = create_engine(pg)
    try:
        with engine.connect() as cx:
            def tem(sql: str, **args) -> bool:
                return cx.execute(text(sql), args).scalar()

            tabela = "SELECT has_table_privilege(:p, 'notas_desatualizadas', :priv)"
            coluna = "SELECT has_column_privilege(:p, 'notas_desatualizadas', :col, 'UPDATE')"
            sequencia = "SELECT has_sequence_privilege(:p, 'notas_desatualizadas_id_seq', :priv)"
            assert {priv: tem(tabela, p=ESCRITA, priv=priv) for priv in ("SELECT", "INSERT", "UPDATE", "DELETE",
                                                                         "TRUNCATE")} == {
                "SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
            assert {col: tem(coluna, p=ESCRITA, col=col) for col in ("id", "criado_em", "caminho", "motivo", "autor",
                                                                     "desfeito")} == {
                "id": False, "criado_em": False, "caminho": False, "motivo": False, "autor": False, "desfeito": True}
            assert {priv: tem(tabela, p=LEITURA, priv=priv) for priv in ("SELECT", "INSERT", "UPDATE", "DELETE")} == {
                "SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False}
            assert not any(tem(coluna, p=LEITURA, col=col) for col in ("caminho", "desfeito"))
            assert tem(sequencia, p=ESCRITA, priv="USAGE") and not tem(sequencia, p=LEITURA, priv="USAGE")
    finally:
        engine.dispose()


def _recusado(engine, sql: str, **args) -> bool:
    """True se o Postgres recusa o comando por falta de privilégio. Tudo roda numa transação desfeita no fim."""
    with engine.connect() as cx:
        try:
            cx.execute(text(sql), args)
        except ProgrammingError as e:
            assert "permission denied" in str(e.orig), e
            return True
        finally:
            cx.rollback()
    return False


def test_escrita_so_insere_e_muda_desfeito_e_leitura_so_le(pg):
    escrita, leitura, dono = _como(pg, ESCRITA), _como(pg, LEITURA), create_engine(pg)
    caminho = f"00-inbox/grant-{uuid.uuid4().hex[:8]}.md"
    try:
        with dono.begin() as cx:  # uma marca já gravada, para os UPDATE e DELETE terem alvo
            mid = cx.execute(text("INSERT INTO notas_desatualizadas (caminho, motivo) VALUES (:c, 'teste') "
                                  "RETURNING id"), {"c": caminho}).scalar()
        alvo = {"id": mid}
        assert not _recusado(escrita, "INSERT INTO notas_desatualizadas (caminho, motivo) VALUES (:c, 'x')",
                             c=caminho.replace(".md", "-2.md"))
        assert not _recusado(escrita, "UPDATE notas_desatualizadas SET desfeito = true WHERE id = :id", **alvo)
        assert _recusado(escrita, "UPDATE notas_desatualizadas SET caminho = 'outro.md' WHERE id = :id", **alvo)
        assert _recusado(escrita, "UPDATE notas_desatualizadas SET motivo = 'outro' WHERE id = :id", **alvo)
        assert _recusado(escrita, "DELETE FROM notas_desatualizadas WHERE id = :id", **alvo)
        assert _recusado(escrita, "TRUNCATE notas_desatualizadas")

        assert not _recusado(leitura, "SELECT caminho, motivo FROM notas_desatualizadas WHERE id = :id", **alvo)
        assert _recusado(leitura, "INSERT INTO notas_desatualizadas (caminho, motivo) VALUES ('x.md', 'x')")
        assert _recusado(leitura, "UPDATE notas_desatualizadas SET desfeito = true WHERE id = :id", **alvo)
        assert _recusado(leitura, "DELETE FROM notas_desatualizadas WHERE id = :id", **alvo)

        with dono.connect() as cx:  # nada mudou: todo comando acima foi desfeito ou recusado
            assert cx.execute(text("SELECT caminho, motivo, desfeito FROM notas_desatualizadas WHERE id = :id"),
                              alvo).one() == (caminho, "teste", False)
            cx.execute(text("UPDATE notas_desatualizadas SET desfeito = true WHERE id = :id"), alvo)  # libera o caminho
            cx.commit()
    finally:
        for engine in (escrita, leitura, dono):
            engine.dispose()


def test_ferramentas_rodam_com_os_papeis_de_verdade(pg):
    """marcar, consultar e desfazer com os papéis de leitura e escrita: o UPDATE do SQLAlchemy só muda `desfeito`."""
    escrita, leitura = _como(pg, ESCRITA), _como(pg, LEITURA)
    comandos: list[str] = []
    event.listen(escrita, "before_cursor_execute", lambda _c, _cur, sql, *_: comandos.append(" ".join(sql.split())))
    bancos = Bancos(leitura=sessionmaker(leitura, expire_on_commit=False),
                    escrita=sessionmaker(escrita, expire_on_commit=False))
    mcp = criar_servidor_banco(bancos, TZ)
    marcar, consultar, desfazer = (anyio.run(mcp.get_tool, nome).fn
                                   for nome in ("marcar_desatualizada", "consultar_desatualizadas", "desfazer_registro"))
    caminho = f"00-inbox/ferramenta-{uuid.uuid4().hex[:8]}.md"
    try:
        r = marcar(caminho=caminho, motivo="velha")
        assert r["confirmacao"] == f"Marquei {caminho} como desatualizada (marca {r['id']}). Desfazer?"
        [marca] = consultar(caminho=caminho)
        assert (marca["id"], marca["motivo"]) == (r["id"], "velha") and marca["momento"].endswith("-03:00")

        comandos.clear()
        assert desfazer(tipo="desatualizada", id=r["id"]) == f"Desfeito: marca {r['id']}."
        [update] = [c for c in comandos if c.startswith("UPDATE")]
        # Só a coluna desfeito no SET (o resto do texto depende da versão do SQLAlchemy).
        assert update.startswith("UPDATE notas_desatualizadas SET desfeito=%(desfeito)s"), update
        assert update.split(" SET ")[1].split(" WHERE ")[0].count("=") == 1, update
        assert desfazer(tipo="desatualizada", id=r["id"]) == f"A marca {r['id']} já estava desfeita."
        assert consultar(caminho=caminho) == []

        r2 = marcar(caminho=caminho, motivo="de novo")  # desfeita, a nota pode ser marcada outra vez
        with pytest.raises(Exception, match=f"já está marcada \\(marca {r2['id']}\\)"):
            marcar(caminho=caminho, motivo="repetida")
        desfazer(tipo="desatualizada", id=r2["id"])
    finally:
        escrita.dispose()
        leitura.dispose()

    with Session(create_engine(pg)) as s:
        linhas = s.execute(text("SELECT acao FROM auditoria WHERE tabela = :t AND registro_id IN (:a, :b) ORDER BY id"),
                           {"t": TABELA, "a": r["id"], "b": r2["id"]}).scalars().all()
    assert linhas == ["criar", "desfazer", "criar", "desfazer"]
