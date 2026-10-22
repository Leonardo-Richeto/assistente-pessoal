"""GRANTs e índice único de `sessoes` no Postgres de verdade (Sprint 2b, Passo 11; migração 0006).

Só roda com ASSISTENTE_PG_RASCUNHO = URL do DONO de um banco de RASCUNHO `teste_*` já migrado (alembic upgrade
head), com os papéis do deploy/postgres/01-papeis.sh. Sem a variável, o teste é pulado. Como subir o Postgres de
rascunho: test_desatualizadas_pg.py. O dono troca de papel com SET ROLE: o Postgres confere os privilégios do
papel em vigor, como numa conexão com o usuário de leitura ou de escrita.
"""

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anyio
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from assistente import sessoes
from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from assistente.modelos import Sessao
from test_concorrencia_pg import URL, url  # noqa: F401 (fixture: confere que é um banco teste_* migrado)
from test_desatualizadas_pg import ESCRITA, LEITURA, _como, _recusado

TZ = ZoneInfo("America/Sao_Paulo")

pytestmark = pytest.mark.skipif(not URL, reason="sem ASSISTENTE_PG_RASCUNHO (Postgres de rascunho)")


@pytest.fixture
def pg(url):  # noqa: F811
    engine = create_engine(url)
    try:
        with engine.connect() as cx:
            if cx.execute(text("SELECT to_regclass('sessoes')")).scalar() is None:
                pytest.fail("Banco de rascunho sem a migração 0006: rode alembic upgrade head nele")
    finally:
        engine.dispose()
    return url


def _resumo(sessao: str, fim: datetime, **extra) -> dict:
    base = {"sessao": sessao, "projeto": "assistente-pessoal", "raiz": "/repos/assistente-pessoal",
            "maquina": "rascunho", "inicio": (fim - timedelta(minutes=30)).isoformat(), "fim": fim.isoformat(),
            "duracao_min": 30, "titulo": "teste de GRANT", "arquivos": ["a.py"], "comandos": ["git status"],
            "commits": [], "passagem": False, "motivo_fim": "other", "versao_resumo": 2}
    base.update(extra)
    return base


def test_privilegios_pelo_catalogo(pg):
    engine = create_engine(pg)
    try:
        with engine.connect() as cx:
            def tem(sql: str, **args) -> bool:
                return cx.execute(text(sql), args).scalar()

            tabela = "SELECT has_table_privilege(:p, 'sessoes', :priv)"
            sequencia = "SELECT has_sequence_privilege(:p, 'sessoes_id_seq', :priv)"
            todos = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
            assert {priv: tem(tabela, p=ESCRITA, priv=priv) for priv in todos} == {
                "SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False,
                "REFERENCES": False, "TRIGGER": False}
            assert {priv: tem(tabela, p=LEITURA, priv=priv) for priv in todos} == {
                "SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False, "TRUNCATE": False,
                "REFERENCES": False, "TRIGGER": False}
            # Nenhum UPDATE de coluna escondido (o REVOKE de tabela leva os de coluna junto).
            assert not cx.execute(text("SELECT count(*) FROM information_schema.column_privileges WHERE "
                                       "table_name = 'sessoes' AND privilege_type = 'UPDATE' AND grantee IN (:e, :l)"),
                                  {"e": ESCRITA, "l": LEITURA}).scalar()
            assert tem(sequencia, p=ESCRITA, priv="USAGE") and not tem(sequencia, p=LEITURA, priv="USAGE")
    finally:
        engine.dispose()


def test_escrita_so_insere_e_leitura_so_le(pg):
    escrita, leitura, dono = _como(pg, ESCRITA), _como(pg, LEITURA), create_engine(pg)
    sessao = f"grant-{uuid.uuid4().hex[:12]}"
    colunas = ("sessao, projeto, raiz, maquina, fim, duracao_min, titulo, arquivos, comandos, commits, motivo_fim, "
               "versao_resumo")
    valores = "(:s, 'p', '/r', 'm', now(), 1, 't', '[]', '[]', '[]', 'other', 2)"
    try:
        with dono.begin() as cx:  # uma sessão já gravada, para os UPDATE e DELETE terem alvo
            sid = cx.execute(text(f"INSERT INTO sessoes ({colunas}) VALUES {valores} RETURNING id"),
                             {"s": sessao}).scalar()
        alvo = {"id": sid}
        assert not _recusado(escrita, f"INSERT INTO sessoes ({colunas}) VALUES {valores}", s=sessao + "-2")
        assert not _recusado(escrita, "SELECT titulo FROM sessoes WHERE id = :id", **alvo)
        assert _recusado(escrita, "UPDATE sessoes SET titulo = 'outro' WHERE id = :id", **alvo)
        assert _recusado(escrita, "UPDATE sessoes SET passagem = true WHERE id = :id", **alvo)
        assert _recusado(escrita, "DELETE FROM sessoes WHERE id = :id", **alvo)
        assert _recusado(escrita, "TRUNCATE sessoes")

        assert not _recusado(leitura, "SELECT titulo, comandos FROM sessoes WHERE id = :id", **alvo)
        assert _recusado(leitura, f"INSERT INTO sessoes ({colunas}) VALUES {valores}", s=sessao + "-3")
        assert _recusado(leitura, "UPDATE sessoes SET titulo = 'outro' WHERE id = :id", **alvo)
        assert _recusado(leitura, "DELETE FROM sessoes WHERE id = :id", **alvo)

        with dono.connect() as cx:  # nada mudou: todo comando acima foi desfeito ou recusado
            assert cx.execute(text("SELECT titulo, passagem FROM sessoes WHERE id = :id"), alvo).one() == ("t", False)
            assert cx.execute(text("SELECT count(*) FROM sessoes WHERE sessao LIKE :s"),
                              {"s": sessao + "%"}).scalar() == 1
    finally:
        for engine in (escrita, leitura, dono):
            engine.dispose()


def test_indice_unico_de_sessao_e_fim(pg):
    """O mesmo (sessao, fim) não entra duas vezes, nem com o fim escrito em outro fuso; outro fim entra."""
    dono = create_engine(pg)
    sessao = f"unico-{uuid.uuid4().hex[:12]}"
    fim = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
    try:
        with Session(dono) as s, s.begin():
            s.add(Sessao(**sessoes.validar(_resumo(sessao, fim))))
        with pytest.raises(IntegrityError), Session(dono) as s, s.begin():
            s.add(Sessao(**sessoes.validar(_resumo(sessao, fim) | {"fim": "2026-10-20T10:00:00-03:00"})))
        with Session(dono) as s, s.begin():
            s.add(Sessao(**sessoes.validar(_resumo(sessao, fim + timedelta(hours=1)))))
    finally:
        dono.dispose()


def test_importador_e_consulta_com_os_papeis_de_verdade(pg):
    """Importa com o papel de escrita (INSERT em sessoes e auditoria, SELECT para as repetidas) e consulta com o de
    leitura: os GRANTs bastam para o caminho real, e o importador não pede UPDATE nem DELETE."""
    escrita, leitura = _como(pg, ESCRITA), _como(pg, LEITURA)
    comandos: list[str] = []
    event.listen(escrita, "before_cursor_execute", lambda _c, _cur, sql, *_: comandos.append(sql.split()[0].upper()))
    prefixo = uuid.uuid4().hex[:8]
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    a = _resumo(f"{prefixo}-aaaa", agora - timedelta(hours=2), projeto=f"proj-{prefixo}", passagem=False)
    a2 = _resumo(f"{prefixo}-aaaa", agora - timedelta(hours=1), projeto=f"proj-{prefixo}", passagem=True,
                 titulo="retomada")
    b = _resumo(f"{prefixo}-bbbb", agora - timedelta(hours=3), projeto=f"proj-{prefixo}")
    entrada = b"".join(json.dumps(x).encode() + b"\n" for x in (a, b, a, {"sessao": "x"}))
    try:
        r = sessoes.importar(io.BytesIO(entrada), escrita)
        assert r["aceitas"] == [a["sessao"], b["sessao"]] and r["repetidas"] == [a["sessao"]]
        assert [x["linha"] for x in r["recusadas"]] == [4]
        r2 = sessoes.importar(io.BytesIO(json.dumps(a2).encode() + b"\n" + json.dumps(b).encode()), escrita)
        assert r2["aceitas"] == [a["sessao"]] and r2["repetidas"] == [b["sessao"]]
        assert set(comandos) <= {"SELECT", "INSERT", "BEGIN", "COMMIT", "ROLLBACK", "SHOW", "SET"}, set(comandos)

        bancos = Bancos(leitura=sessionmaker(leitura, expire_on_commit=False),
                        escrita=sessionmaker(escrita, expire_on_commit=False))
        consultar = anyio.run(criar_servidor_banco(bancos, TZ).get_tool, "consultar_sessoes").fn
        resposta = consultar(projeto=prefixo, dias=1)
        assert resposta["cortado"] is False
        lista = resposta["sessoes"]
        assert [(x["sessao"], x["texto_de_fora"]["titulo"], x["passagem"]) for x in lista] == [
            (a["sessao"], "retomada", True), (b["sessao"], "teste de GRANT", False)]
        assert lista[0]["fim"].endswith("-03:00")
        assert consultar(projeto=prefixo, sem_passagem=True)["sessoes"][0]["sessao"] == b["sessao"]
    finally:
        escrita.dispose()
        leitura.dispose()

    with Session(create_engine(pg)) as s:
        dados = s.execute(text("SELECT dados FROM auditoria WHERE ferramenta = 'sessoes_importar' ORDER BY id DESC "
                               "LIMIT 2")).scalars().all()
    assert dados == [{"quantidade": 1, "repetidas": 1, "recusadas": 0, "maquinas": ["rascunho"]},
                     {"quantidade": 2, "repetidas": 1, "recusadas": 1, "maquinas": ["rascunho"]}]
