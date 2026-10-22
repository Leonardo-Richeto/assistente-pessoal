"""Notas marcadas como desatualizadas (Sprint 2b, Passo 8; ficha 5, regra 8).

`marcar_desatualizada`, `consultar_desatualizadas`, o desfazer com tipo `desatualizada`, a lista do lint
(`python -m assistente.desatualizadas`) e a migração 0005 em SQLite. Os GRANTs no Postgres estão em
test_desatualizadas_pg.py.
"""

import os
import subprocess
import sys

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from assistente import desatualizadas
from assistente.banco import TAMANHO_MOTIVO
from assistente.modelos import Auditoria, Chamada, NotaDesatualizada
from test_nota_vault import INVALIDOS
from test_registro import SERVIDOR, _alembic, app, recebidas, url  # noqa: F401 (fixtures)

NOTA = "60-planos/carro.md"
MOTIVO = "Fala do carro vendido em 2025."


def _auditoria(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def _chamadas(url, ferramenta) -> list[Chamada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Chamada).where(Chamada.ferramenta == ferramenta).order_by(Chamada.id)))


def _marcas(url) -> list[NotaDesatualizada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(NotaDesatualizada).order_by(NotaDesatualizada.id)))


async def _chamar(c, nome, **args):
    return (await c.call_tool(nome, args)).data


# ---------------- Marcar ----------------

async def test_marcar_grava_marca_auditoria_e_chamada(app, url):
    async with Client(app) as c:
        r = await _chamar(c, "marcar_desatualizada", caminho=f"  {NOTA} ", motivo=f"  {MOTIVO}\n", modelo="claude-opus-5-5")
    assert r == {"id": 1, "confirmacao": f"Marquei {NOTA} como desatualizada (marca 1). Desfazer?"}
    [marca] = _marcas(url)
    assert (marca.caminho, marca.motivo, marca.autor, marca.desfeito) == (NOTA, MOTIVO, None, False)
    assert marca.criado_em is not None
    [linha] = _auditoria(url)
    assert (linha.ferramenta, linha.tabela, linha.registro_id, linha.acao) == (
        "marcar_desatualizada", "notas_desatualizadas", r["id"], "criar")
    assert linha.dados == {"caminho": NOTA, "motivo": MOTIVO}
    assert [(ch.resultado, ch.auditoria_id, ch.modelo_declarado) for ch in _chamadas(url, "marcar_desatualizada")] == [
        ("ok", linha.id, "claude-opus-5-5")]


async def test_marcar_de_novo_a_mesma_nota_e_recusado(app, url):
    async with Client(app) as c:
        r = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO)
        with pytest.raises(ToolError, match=f"^{NOTA} já está marcada \\(marca {r['id']}\\)\\.$"):
            await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo="outro motivo")
        # Outra nota passa.
        await _chamar(c, "marcar_desatualizada", caminho="00-inbox/outra.md", motivo=MOTIVO)
    assert [m.caminho for m in _marcas(url)] == [NOTA, "00-inbox/outra.md"]
    assert [a.acao for a in _auditoria(url)] == ["criar", "criar"]
    assert [ch.resultado for ch in _chamadas(url, "marcar_desatualizada")] == ["ok", "erro", "ok"]


async def test_marca_desfeita_libera_marcar_de_novo(app, url):
    async with Client(app) as c:
        r1 = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO)
        await _chamar(c, "desfazer_registro", tipo="desatualizada", id=r1["id"])
        r2 = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo="de novo")
    assert r2["id"] == r1["id"] + 1
    assert [(m.id, m.desfeito) for m in _marcas(url)] == [(r1["id"], True), (r2["id"], False)]


def test_indice_unico_segura_duas_marcas_em_vigor(url):
    """A corrida (duas chamadas passam da conferência juntas) para no índice único parcial."""
    engine = create_engine(url)
    with Session(engine) as s, s.begin():
        s.add(NotaDesatualizada(caminho=NOTA, motivo="a", desfeito=True))
        s.add(NotaDesatualizada(caminho=NOTA, motivo="b"))
    with pytest.raises(IntegrityError), Session(engine) as s, s.begin():
        s.add(NotaDesatualizada(caminho=NOTA, motivo="c"))


async def test_corrida_na_gravacao_vira_a_mesma_recusa(app, url, monkeypatch):
    """Se outra chamada grava entre a conferência e o INSERT, o IntegrityError vira a frase de sempre."""
    async with Client(app) as c:
        r = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO)
        # Simula a corrida: a conferência não vê a marca que já existe; o INSERT esbarra no índice.
        monkeypatch.setattr(Session, "scalar", _primeira_none(Session.scalar))
        with pytest.raises(ToolError, match=f"^{NOTA} já está marcada \\(marca {r['id']}\\)\\.$"):
            await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo="outro")
    assert len(_marcas(url)) == 1
    assert [a.acao for a in _auditoria(url)] == ["criar"]


def _primeira_none(original):
    """Session.scalar que devolve None na primeira chamada (a conferência) e o valor real depois."""
    chamadas = []

    def scalar(self, *a, **k):
        chamadas.append(1)
        return None if len(chamadas) == 1 else original(self, *a, **k)

    return scalar


@pytest.mark.parametrize("caminho", INVALIDOS + ["", "   "])
async def test_caminho_invalido_e_recusado_sem_gravar(app, url, caminho):
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Caminho de nota inválido|caracteres|Informe o caminho"):
            await _chamar(c, "marcar_desatualizada", caminho=caminho, motivo=MOTIVO)
    assert _marcas(url) == [] and _auditoria(url) == []


async def test_motivo_longo_ou_vazio_e_recusado(app, url):
    async with Client(app) as c:
        with pytest.raises(ToolError, match=f"O motivo tem {TAMANHO_MOTIVO + 1} caracteres; resuma em até 500"):
            await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo="x" * (TAMANHO_MOTIVO + 1))
        with pytest.raises(ToolError, match="Diga em uma frase por que"):
            await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo="  \n ")
        assert _marcas(url) == []
        # No limite, contado sem os espaços das pontas, passa.
        await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=" " + "x" * TAMANHO_MOTIVO + " ")
    assert len(_marcas(url)[0].motivo) == TAMANHO_MOTIVO


# ---------------- Consultar ----------------

async def test_consultar_lista_em_vigor_mais_novas_primeiro(app, url):
    async with Client(app) as c:
        assert await _chamar(c, "consultar_desatualizadas") == []
        a = await _chamar(c, "marcar_desatualizada", caminho="00-inbox/a.md", motivo="velha")
        b = await _chamar(c, "marcar_desatualizada", caminho="00-inbox/b.md", motivo="errada")
        x = await _chamar(c, "marcar_desatualizada", caminho="00-inbox/x.md", motivo="desfeita")
        await _chamar(c, "desfazer_registro", tipo="desatualizada", id=x["id"])
        todas = await _chamar(c, "consultar_desatualizadas")
        so_a = await _chamar(c, "consultar_desatualizadas", caminho=" 00-inbox/a.md ")
        so_x = await _chamar(c, "consultar_desatualizadas", caminho="00-inbox/x.md")
        vazio = await _chamar(c, "consultar_desatualizadas", caminho="  ")
        with pytest.raises(ToolError, match="Caminho de nota inválido"):
            await _chamar(c, "consultar_desatualizadas", caminho="../fora.md")
    assert [(m["id"], m["caminho"], m["motivo"], m["autor"]) for m in todas] == [
        (b["id"], "00-inbox/b.md", "errada", None), (a["id"], "00-inbox/a.md", "velha", None)]
    assert set(todas[0]) == {"id", "caminho", "motivo", "momento", "autor"}
    assert todas[0]["momento"].endswith("-03:00")  # fuso local (America/Sao_Paulo)
    assert [m["id"] for m in so_a] == [a["id"]]
    assert so_x == []
    assert vazio == todas
    # Leitura: só a linha de `chamadas`, nenhuma na auditoria.
    assert [x.acao for x in _auditoria(url)] == ["criar", "criar", "criar", "desfazer"]


# ---------------- Desfazer ----------------

async def test_desfazer_marca_grava_auditoria_e_repete_sem_mudar(app, url):
    async with Client(app) as c:
        r = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO)
        d1 = await _chamar(c, "desfazer_registro", tipo="desatualizada", id=r["id"], modelo="claude-opus-5-5")
        d2 = await _chamar(c, "desfazer_registro", tipo="desatualizada", id=r["id"])
        with pytest.raises(ToolError, match="^Não achei marca com id 999\\.$"):
            await _chamar(c, "desfazer_registro", tipo="desatualizada", id=999)
        aud = await _chamar(c, "consultar_auditoria", tabela="notas_desatualizadas")
    assert d1 == f"Desfeito: marca {r['id']}."
    assert d2 == f"A marca {r['id']} já estava desfeita."
    [marca] = _marcas(url)
    assert (marca.desfeito, marca.caminho, marca.motivo) == (True, NOTA, MOTIVO)  # nada mais muda
    linhas = _auditoria(url)
    assert [(x.ferramenta, x.tabela, x.registro_id, x.acao, x.dados) for x in linhas] == [
        ("marcar_desatualizada", "notas_desatualizadas", r["id"], "criar", {"caminho": NOTA, "motivo": MOTIVO}),
        ("desfazer_registro", "notas_desatualizadas", r["id"], "desfazer", {}),
    ]
    assert [a["acao"] for a in aud] == ["desfazer", "criar"]
    desfazer = _chamadas(url, "desfazer_registro")
    assert [(ch.resultado, ch.auditoria_id, ch.modelo_declarado) for ch in desfazer] == [
        ("ok", linhas[1].id, "claude-opus-5-5"), ("ok", None, None), ("erro", None, None)]


@pytest.mark.parametrize("tipo", ["gasto", "desatualizada"])
async def test_desfazer_le_a_linha_com_for_update(app, url, tipo):
    """O SELECT do desfazer pede FOR UPDATE: dois desfazer ao mesmo tempo não gravam duas linhas na auditoria.

    O SQLite ignora a trava; aqui o teste confere o pedido e que o caminho continua funcionando. A corrida de
    verdade está em test_concorrencia_pg.py.
    """
    tabela = {"gasto": "gastos", "desatualizada": "notas_desatualizadas"}[tipo]
    selects: list[bool] = []

    def anotar(estado):
        if estado.is_select and {m.class_.__tablename__ for m in estado.all_mappers} == {tabela}:
            selects.append(estado.statement._for_update_arg is not None)

    async with Client(app) as c:
        if tipo == "gasto":
            rid = (await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y"))["id"]
        else:
            rid = (await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO))["id"]
        event.listen(Session, "do_orm_execute", anotar)
        try:
            d1 = await _chamar(c, "desfazer_registro", tipo=tipo, id=rid)
            d2 = await _chamar(c, "desfazer_registro", tipo=tipo, id=rid)
        finally:
            event.remove(Session, "do_orm_execute", anotar)
    assert d1.startswith("Desfeito:") and "já estava" in d2
    assert selects == [True, True]
    assert [x.acao for x in _auditoria(url) if x.tabela == tabela] == ["criar", "desfazer"]


async def test_desfazer_tipos_nao_se_misturam(app, url):
    """O id da marca não desfaz o gasto de mesmo id, e vice-versa."""
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        m = await _chamar(c, "marcar_desatualizada", caminho=NOTA, motivo=MOTIVO)
        assert g["id"] == m["id"] == 1
        assert await _chamar(c, "desfazer_registro", tipo="gasto", id=1) == "Desfeito: gasto 1."
        assert [x["id"] for x in await _chamar(c, "consultar_desatualizadas")] == [1]
        with pytest.raises(ToolError, match="^Não achei gasto com id 2\\.$"):
            await _chamar(c, "desfazer_registro", tipo="gasto", id=2)


async def test_descricoes_das_ferramentas(app):
    async with Client(app) as c:
        ferramentas = {t.name: t for t in await c.list_tools()}
    marcar, consultar = ferramentas["marcar_desatualizada"], ferramentas["consultar_desatualizadas"]
    assert marcar.annotations.read_only_hint is False and consultar.annotations.read_only_hint is True
    assert set(marcar.input_schema["required"]) == {"caminho", "motivo"}
    assert "modelo" in marcar.input_schema["properties"]
    assert "desatualizada" in str(ferramentas["desfazer_registro"].input_schema["properties"]["tipo"])


# ---------------- Lista do lint (python -m assistente.desatualizadas) ----------------

async def test_lista_do_lint_uma_linha_por_marca_em_vigor(app, url, monkeypatch, capsys):
    async with Client(app) as c:
        await _chamar(c, "marcar_desatualizada", caminho="00-inbox/a.md", motivo="velha\ncom quebra")
        x = await _chamar(c, "marcar_desatualizada", caminho="00-inbox/x.md", motivo="desfeita")
        await _chamar(c, "desfazer_registro", tipo="desatualizada", id=x["id"])
        await _chamar(c, "marcar_desatualizada", caminho="00-inbox/b.md", motivo="errada")
    monkeypatch.setenv("DATABASE_URL_LEITURA", url)
    assert desatualizadas.main() == 0
    saida = capsys.readouterr()
    assert saida.err == ""
    linhas = saida.out.splitlines()
    assert len(linhas) == 2
    assert linhas[0].startswith("- 00-inbox/b.md — errada (marca 3, 20") and linhas[0].endswith(")")
    assert linhas[1].startswith("- 00-inbox/a.md — velha com quebra (marca 1, ")


def test_lista_do_lint_vazia_nao_imprime_nada(url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL_LEITURA", url)
    assert desatualizadas.main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("valor", [None, "sqlite:////pasta/que/nao/existe/x.db"])
def test_lista_do_lint_sem_banco_sai_com_2(monkeypatch, capsys, valor):
    if valor is None:
        monkeypatch.delenv("DATABASE_URL_LEITURA", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL_LEITURA", valor)
    assert desatualizadas.main() == 2
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err.startswith("desatualizadas: ")
    assert "pasta/que/nao" not in saida.err  # a URL (com senha, no Postgres) não vai para o log


def test_lista_do_lint_pela_linha_de_comando(url):
    r = subprocess.run([sys.executable, "-m", "assistente.desatualizadas"], cwd=SERVIDOR, capture_output=True,
                       text=True, env={**os.environ, "DATABASE_URL_LEITURA": url})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ---------------- Migração 0005 ----------------

def test_migracao_0005_sobe_desce_sem_apagar_e_sobe_de_novo(tmp_path):
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "0004")
    engine = create_engine(url)
    assert not inspect(engine).has_table("notas_desatualizadas")

    _alembic(url, "upgrade", "0005")
    engine.dispose()
    colunas = {c["name"]: c for c in inspect(engine).get_columns("notas_desatualizadas")}
    assert list(colunas) == ["id", "criado_em", "caminho", "motivo", "autor", "desfeito"]
    assert {n for n, c in colunas.items() if c["nullable"]} == {"autor"}
    [indice] = inspect(engine).get_indexes("notas_desatualizadas")
    assert (indice["name"], indice["column_names"], bool(indice["unique"])) == (
        "ix_notas_desatualizadas_caminho_em_vigor", ["caminho"], True)
    with engine.begin() as cx:
        cx.execute(text("INSERT INTO notas_desatualizadas (criado_em, caminho, motivo) "
                        "VALUES (CURRENT_TIMESTAMP, '00-inbox/a.md', 'velha')"))
        assert cx.execute(text("SELECT desfeito FROM notas_desatualizadas")).scalar() in (0, False, "false")

    # Descer não apaga a tabela nem as marcas.
    _alembic(url, "downgrade", "0004")
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
        assert cx.execute(text("SELECT caminho, motivo FROM notas_desatualizadas")).all() == [("00-inbox/a.md", "velha")]

    # Subir de novo reaproveita a tabela que ficou.
    _alembic(url, "upgrade", "0005")
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
        assert cx.execute(text("SELECT count(*) FROM notas_desatualizadas")).scalar() == 1


def _sql_offline(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args, "--sql"], cwd=SERVIDOR, capture_output=True,
                          text=True, env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})


def test_migracao_0005_grants_no_postgres():
    """SQL do Postgres gerado pela 0005 (modo --sql, sem banco): cria a tabela e dá só os GRANTs da ficha."""
    r = _sql_offline("upgrade", "0004:0005")
    assert r.returncode == 0, r.stderr
    sql = [linha.strip().rstrip(";") for linha in r.stdout.splitlines()]
    grants = [linha for linha in sql if linha.startswith(("GRANT", "REVOKE"))]
    assert grants == [
        "REVOKE ALL ON TABLE notas_desatualizadas FROM assistente_escrita, assistente_leitura",
        "REVOKE ALL ON SEQUENCE notas_desatualizadas_id_seq FROM assistente_escrita, assistente_leitura",
        "GRANT SELECT, INSERT ON TABLE notas_desatualizadas TO assistente_escrita",
        "GRANT UPDATE (desfeito) ON TABLE notas_desatualizadas TO assistente_escrita",
        "GRANT USAGE, SELECT ON SEQUENCE notas_desatualizadas_id_seq TO assistente_escrita",
        "GRANT SELECT ON TABLE notas_desatualizadas TO assistente_leitura",
    ]
    assert "CREATE UNIQUE INDEX ix_notas_desatualizadas_caminho_em_vigor ON notas_desatualizadas (caminho) " \
           "WHERE NOT desfeito" in sql
    assert not [linha for linha in sql if linha.startswith(("DROP", "DELETE", "ALTER"))]


def test_migracao_0005_desce_offline_sem_apagar():
    r = _sql_offline("downgrade", "0005:0004")
    assert r.returncode == 0, r.stderr
    assert "DROP" not in r.stdout
    assert "UPDATE alembic_version SET version_num='0004'" in r.stdout
