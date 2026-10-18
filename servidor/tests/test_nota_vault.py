"""Vínculo banco → nota do vault (Passo 8c; ficha 1, item 6).

Coluna `nota_vault` em gastos, ponto e atividades (migração 0004), parâmetro nas `registrar_*`,
`vincular_nota` auditada e o desfazer do vínculo por `desfazer_registro` com tipo `vinculo`.
"""

import os
import subprocess
import sys
import unicodedata

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from assistente.banco import caminho_da_nota
from assistente.modelos import Auditoria, Chamada, Gasto
from test_registro import SERVIDOR, _alembic, app, recebidas, url  # noqa: F401 (fixtures)

INVALIDOS = [
    "/00-inbox/nota.md",  # barra inicial
    "../fora.md",
    "00-inbox/../../fora.md",
    "00-inbox/a..b.md",  # '..' em qualquer lugar
    "00-inbox/nota.txt",
    "00-inbox/nota",
    "00-inbox\\nota.md",
    "00-inbox//nota.md",
    "./nota.md",
    "00-inbox/.md",
    "00-inbox/no\nta.md",
    "a" * 298 + ".md",  # 301 caracteres
    # Revisor do 8c:
    "00-inbox/reuniao: pauta.md",  # ':' em qualquer lugar
    "C:/notas/x.md",  # unidade do Windows
    "C:\\notas\\x.md",
    "~/notas/x.md",
    ".obsidian/workspace.md",  # pasta oculta
    "00-inbox/.oculta/x.md",
    "00-inbox /nota.md",  # espaço no fim de um nome
    "00-inbox/ nota.md",  # espaço no começo de um nome
    "00-inbox/no\x00ta.md",  # byte nulo
    "\uff0e\uff0e/fora.md",  # '．．' (ponto de largura total) vira '..' no NFKC
    "\u2024\u2024/fora.md",  # '․․' (one dot leader) vira '..' no NFKC
    "\uff0f00-inbox/x.md",  # '／' no começo vira '/' no NFKC
    "00-inbox\uff3cx.md",  # '＼' vira barra invertida no NFKC
]


def _auditoria(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def _chamadas(url) -> list[Chamada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Chamada).order_by(Chamada.id)))


async def _chamar(c, nome, **args):
    return (await c.call_tool(nome, args)).data


DIAS = {"inicio": "2020-01-01", "fim": "2099-12-31"}


# ---------------- Formato do caminho ----------------

@pytest.mark.parametrize("caminho", ["00-inbox/nota.md", "10-projetos/assistente-pessoal/Reunião com João.md", "a.md",
                                     "50-diario/2026/2026-10-20.md"])
def test_caminho_valido_passa(caminho):
    assert caminho_da_nota(caminho) == caminho
    assert caminho_da_nota(f"  {caminho} ") == caminho


def test_caminho_e_gravado_em_nfc():
    decomposto = unicodedata.normalize("NFD", "00-inbox/Reunião com João.md")
    assert caminho_da_nota(decomposto) == unicodedata.normalize("NFC", decomposto) != decomposto


def test_limite_de_300_vale_para_o_caminho_limpo():
    no_limite = "a" * 297 + ".md"
    assert caminho_da_nota(f"   {no_limite}   ") == no_limite  # 306 com os espaços; 300 limpo


@pytest.mark.parametrize("vazio", [None, "", "   "])
def test_caminho_vazio_e_sem_nota(vazio):
    assert caminho_da_nota(vazio) is None


@pytest.mark.parametrize("caminho", INVALIDOS)
def test_caminho_invalido_e_recusado(caminho):
    with pytest.raises(ToolError, match="Caminho de nota inválido|caracteres"):
        caminho_da_nota(caminho)


@pytest.mark.parametrize("caminho", INVALIDOS)
async def test_registrar_e_vincular_recusam_caminho_invalido_sem_gravar(app, url, caminho):
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        with pytest.raises(ToolError):
            await _chamar(c, "registrar_gasto", valor=2, descricao="z", categoria="y", nota_vault=caminho)
        with pytest.raises(ToolError):
            await _chamar(c, "registrar_atividade", descricao="z", nota_vault=caminho)
        with pytest.raises(ToolError):
            await _chamar(c, "registrar_ponto", tipo="entrada", nota_vault=caminho)
        with pytest.raises(ToolError):
            await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho=caminho)
        gastos = (await _chamar(c, "consultar_gastos", inicio="2020-01-01", fim="2099-12-31"))["gastos"]
    assert [(x["id"], x["nota_vault"]) for x in gastos] == [(g["id"], None)]
    assert [a.acao for a in _auditoria(url)] == ["criar"]  # nada além do primeiro gasto


# ---------------- Registrar com nota e consultar ----------------

async def test_registrar_com_nota_e_consultar(app, url):
    async with Client(app) as c:
        await _chamar(c, "registrar_gasto", valor=10, descricao="Livro", categoria="estudo", data="2026-10-15",
                      nota_vault=" 00-inbox/livro.md ")
        await _chamar(c, "registrar_gasto", valor=5, descricao="Café", categoria="lazer", data="2026-10-15")
        await _chamar(c, "registrar_ponto", tipo="entrada", momento="2026-10-15T08:00:00", nota_vault="00-inbox/dia.md")
        await _chamar(c, "registrar_atividade", descricao="Estudei Postgres", momento="2026-10-15T20:00:00",
                      nota_vault="00-inbox/estudo-postgres.md")
        await _chamar(c, "registrar_atividade", descricao="Corrida", momento="2026-10-15T07:00:00", nota_vault="")
        gastos = (await _chamar(c, "consultar_gastos", inicio="2026-10-15", fim="2026-10-15"))["gastos"]
        ponto = (await _chamar(c, "consultar_ponto", inicio="2026-10-15", fim="2026-10-15"))["registros"]
        atividades = await _chamar(c, "consultar_atividades", inicio="2026-10-15", fim="2026-10-15")
    assert [g["nota_vault"] for g in gastos] == ["00-inbox/livro.md", None]
    assert [p["nota_vault"] for p in ponto] == ["00-inbox/dia.md"]
    assert [(a["descricao"], a["nota_vault"]) for a in atividades] == [
        ("Corrida", None), ("Estudei Postgres", "00-inbox/estudo-postgres.md")]
    # A auditoria do `criar` leva o caminho (só o caminho, como o resto dos dados do registro).
    criar = [a.dados.get("nota_vault") for a in _auditoria(url) if a.acao == "criar"]
    assert criar == ["00-inbox/livro.md", None, "00-inbox/dia.md", "00-inbox/estudo-postgres.md", None]


# ---------------- vincular_nota ----------------

async def test_vincular_nota_grava_audita_e_troca(app, url):
    async with Client(app) as c:
        a = await _chamar(c, "registrar_atividade", descricao="Estudei Postgres", momento="2026-10-15T20:00:00")
        v1 = await _chamar(c, "vincular_nota", tipo="atividade", id=a["id"], caminho="00-inbox/estudo.md",
                           modelo="claude-opus-5-5")
        v2 = await _chamar(c, "vincular_nota", tipo="atividade", id=a["id"], caminho="00-inbox/estudo-postgres.md")
        atividades = await _chamar(c, "consultar_atividades", inicio="2026-10-15", fim="2026-10-15")
    # Sem `id` no retorno: o id é da auditoria, e um `id` solto convidaria desfazer_registro(tipo="atividade", id).
    assert set(v1) == {"vinculo", "desfazer", "confirmacao"}
    assert v1["desfazer"] == {"tipo": "vinculo", "id": v1["vinculo"]}
    assert v1["confirmacao"] == (f"Nota ligada à atividade {a['id']}: 00-inbox/estudo.md "
                                 f"(desfazer: tipo vinculo, id {v1['vinculo']}). Desfazer?")
    assert v2["confirmacao"] == (f"Nota ligada à atividade {a['id']}: 00-inbox/estudo-postgres.md (antes: "
                                 f"00-inbox/estudo.md) (desfazer: tipo vinculo, id {v2['vinculo']}). Desfazer?")
    assert atividades[0]["nota_vault"] == "00-inbox/estudo-postgres.md"

    linhas = _auditoria(url)
    # Escrita do banco: sem linha `escrever` do registro, só as do próprio banco.
    assert [(x.ferramenta, x.tabela, x.registro_id, x.acao) for x in linhas] == [
        ("registrar_atividade", "atividades", a["id"], "criar"),
        ("vincular_nota", "atividades", a["id"], "vincular"),
        ("vincular_nota", "atividades", a["id"], "vincular"),
    ]
    assert [x.id for x in linhas[1:]] == [v1["vinculo"], v2["vinculo"]]
    assert linhas[1].dados == {"caminho": "00-inbox/estudo.md"}
    assert linhas[2].dados == {"caminho": "00-inbox/estudo-postgres.md", "anterior": "00-inbox/estudo.md"}
    assert linhas[1].autor is None  # sem token nos testes em memória
    # A linha de `chamadas` aponta para a auditoria do vínculo e guarda o modelo declarado.
    chamadas = [ch for ch in _chamadas(url) if ch.ferramenta == "vincular_nota"]
    assert [(ch.resultado, ch.auditoria_id, ch.modelo_declarado) for ch in chamadas] == [
        ("ok", v1["vinculo"], "claude-opus-5-5"), ("ok", v2["vinculo"], None)]


async def test_vincular_nota_ao_gasto_concorda_no_masculino(app, url):
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        v = await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho="00-inbox/x.md")
        r = await _chamar(c, "desfazer_registro", tipo="vinculo", id=v["vinculo"])
    assert v["confirmacao"].startswith(f"Nota ligada ao gasto {g['id']}: 00-inbox/x.md (desfazer:")
    assert r == f"Desfeito: vínculo {v['vinculo']}. O gasto {g['id']} ficou sem nota."


async def test_vincular_nota_e_destrutiva_e_idempotente(app):
    async with Client(app) as c:
        ferramenta = next(t for t in await c.list_tools() if t.name == "vincular_nota")
    a = ferramenta.annotations
    assert (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint) == (False, True, True, False)
    # O limite de 300 vale no caminho limpo: não vai no schema.
    assert "maxLength" not in ferramenta.input_schema["properties"]["caminho"]


@pytest.mark.parametrize("tipo,registrar,texto", [
    ("gasto", ("registrar_gasto", {"valor": 1, "descricao": "x", "categoria": "y"}), "o gasto {id} já está ligado"),
    ("atividade", ("registrar_atividade", {"descricao": "x"}), "a atividade {id} já está ligada"),
])
async def test_vincular_mesmo_caminho_nao_muda_nada(app, url, tipo, registrar, texto):
    async with Client(app) as c:
        reg = await _chamar(c, registrar[0], **registrar[1], nota_vault="00-inbox/x.md")
        r = await _chamar(c, "vincular_nota", tipo=tipo, id=reg["id"], caminho="00-inbox/x.md")
    assert r["vinculo"] is None and r["desfazer"] is None
    assert r["confirmacao"] == f"Nada mudou: {texto.format(id=reg['id'])} a 00-inbox/x.md. Nada a desfazer."
    assert [a.acao for a in _auditoria(url)] == ["criar"]


async def test_vincular_registro_inexistente_ou_desfeito_da_erro(app, url):
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Não achei ponto com id 99"):
            await _chamar(c, "vincular_nota", tipo="ponto", id=99, caminho="00-inbox/x.md")
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        a = await _chamar(c, "registrar_atividade", descricao="x")
        await _chamar(c, "desfazer_registro", tipo="gasto", id=g["id"])
        assert await _chamar(c, "desfazer_registro", tipo="atividade", id=a["id"]) == f"Desfeito: atividade {a['id']}."
        assert (await _chamar(c, "desfazer_registro", tipo="atividade", id=a["id"])
                == f"A atividade {a['id']} já estava desfeita.")
        assert await _chamar(c, "desfazer_registro", tipo="gasto", id=g["id"]) == f"O gasto {g['id']} já estava desfeito."
        with pytest.raises(ToolError, match=f"O gasto {g['id']} está desfeito; não dá para ligar nota"):
            await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho="00-inbox/x.md")
        with pytest.raises(ToolError, match=f"A atividade {a['id']} está desfeita; não dá para ligar nota"):
            await _chamar(c, "vincular_nota", tipo="atividade", id=a["id"], caminho="00-inbox/x.md")
    assert [x.acao for x in _auditoria(url)] == ["criar", "criar", "desfazer", "desfazer"]
    with Session(create_engine(url)) as s:
        assert s.get(Gasto, g["id"]).nota_vault is None


# ---------------- Desfazer o vínculo ----------------

async def test_desfazer_vinculo_volta_a_nota_anterior_sem_apagar(app, url):
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=10, descricao="Livro", categoria="estudo", data="2026-10-15",
                          nota_vault="00-inbox/livro.md")
        v = await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho="00-inbox/livro-postgres.md")
        r = await _chamar(c, "desfazer_registro", **v["desfazer"])
        de_novo = await _chamar(c, "desfazer_registro", **v["desfazer"])
        gastos = (await _chamar(c, "consultar_gastos", inicio="2026-10-15", fim="2026-10-15"))["gastos"]
    assert r == f"Desfeito: vínculo {v['vinculo']}. O gasto {g['id']} voltou para 00-inbox/livro.md."
    assert de_novo == f"O vínculo {v['vinculo']} já estava desfeito."
    # O gasto continua valendo; só a nota voltou.
    assert [(x["id"], x["nota_vault"]) for x in gastos] == [(g["id"], "00-inbox/livro.md")]
    linhas = _auditoria(url)
    assert [x.acao for x in linhas] == ["criar", "vincular", "desfazer_vinculo"]
    assert (linhas[2].ferramenta, linhas[2].tabela, linhas[2].registro_id) == ("desfazer_registro", "gastos", g["id"])
    assert linhas[2].dados == {"vinculo": v["vinculo"], "caminho": "00-inbox/livro.md",
                               "anterior": "00-inbox/livro-postgres.md"}
    # O caminho desfeito continua na auditoria (nada é apagado).
    assert linhas[1].dados["caminho"] == "00-inbox/livro-postgres.md"


async def test_desfazer_primeiro_vinculo_deixa_sem_nota(app, url):
    async with Client(app) as c:
        p = await _chamar(c, "registrar_ponto", tipo="entrada", momento="2026-10-15T08:00:00")
        v = await _chamar(c, "vincular_nota", tipo="ponto", id=p["id"], caminho="00-inbox/dia.md")
        r = await _chamar(c, "desfazer_registro", tipo="vinculo", id=v["vinculo"])
        ponto = (await _chamar(c, "consultar_ponto", inicio="2026-10-15", fim="2026-10-15"))["registros"]
    assert r.endswith(f"O ponto {p['id']} ficou sem nota.")
    assert [(x["id"], x["nota_vault"]) for x in ponto] == [(p["id"], None)]
    # O mesmo caminho pode ser ligado de novo: novo vínculo, nova linha.
    async with Client(app) as c:
        v2 = await _chamar(c, "vincular_nota", tipo="ponto", id=p["id"], caminho="00-inbox/dia.md")
        # O desfazer antigo não pega carona no vínculo novo.
        assert (await _chamar(c, "desfazer_registro", tipo="vinculo", id=v["vinculo"])).endswith("já estava desfeito.")
    assert v2["vinculo"] != v["vinculo"]
    with Session(create_engine(url)) as s:
        assert s.scalars(select(Auditoria.acao).order_by(Auditoria.id)).all() == [
            "criar", "vincular", "desfazer_vinculo", "vincular"]


async def test_desfazer_vinculo_antigo_depois_de_outro_e_recusado(app, url):
    async with Client(app) as c:
        a = await _chamar(c, "registrar_atividade", descricao="x")
        v1 = await _chamar(c, "vincular_nota", tipo="atividade", id=a["id"], caminho="00-inbox/um.md")
        v2 = await _chamar(c, "vincular_nota", tipo="atividade", id=a["id"], caminho="00-inbox/dois.md")
        with pytest.raises(ToolError, match=f"O vínculo {v1['vinculo']} não é o mais novo da atividade {a['id']}: "
                                            f"desfaça antes o vínculo {v2['vinculo']}"):
            await _chamar(c, "desfazer_registro", tipo="vinculo", id=v1["vinculo"])
    assert [x.acao for x in _auditoria(url)] == ["criar", "vincular", "vincular"]


async def test_desfazer_vinculo_so_o_mais_novo_mesmo_com_caminho_repetido(app, url):
    """Revisor do 8c: v1 nenhuma→a, v2 a→b, v3 b→a. Desfazer v1 não pode passar só porque o valor atual é a."""
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        v1, v2, v3 = [(await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho=f"00-inbox/{n}.md"))["vinculo"]
                      for n in ("a", "b", "a")]
        for velho in (v1, v2):
            with pytest.raises(ToolError, match=f"desfaça antes o vínculo {v3}"):
                await _chamar(c, "desfazer_registro", tipo="vinculo", id=velho)
        # Em ordem, do mais novo para o mais velho, cada um volta ao seu anterior.
        assert (await _chamar(c, "desfazer_registro", tipo="vinculo", id=v3)).endswith("voltou para 00-inbox/b.md.")
        with pytest.raises(ToolError, match=f"desfaça antes o vínculo {v2}"):
            await _chamar(c, "desfazer_registro", tipo="vinculo", id=v1)
        assert (await _chamar(c, "desfazer_registro", tipo="vinculo", id=v2)).endswith("voltou para 00-inbox/a.md.")
        assert (await _chamar(c, "desfazer_registro", tipo="vinculo", id=v1)).endswith("ficou sem nota.")
        gastos = (await _chamar(c, "consultar_gastos", **DIAS))["gastos"]
    assert [(x["id"], x["nota_vault"]) for x in gastos] == [(g["id"], None)]
    assert [x.acao for x in _auditoria(url)] == ["criar"] + ["vincular"] * 3 + ["desfazer_vinculo"] * 3


async def test_desfazer_vinculo_com_id_que_nao_e_vinculo_da_erro(app, url):
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        criar = _auditoria(url)[0].id
        for id_ in (criar, 999):
            with pytest.raises(ToolError, match=f"Não achei vínculo de nota com id {id_}"):
                await _chamar(c, "desfazer_registro", tipo="vinculo", id=id_)
        # O gasto com o mesmo id não foi desfeito por engano.
        gastos = (await _chamar(c, "consultar_gastos", **DIAS))["gastos"]
    assert [x["id"] for x in gastos] == [g["id"]]


async def test_desfazer_vinculo_de_registro_desfeito_da_erro(app, url):
    async with Client(app) as c:
        g = await _chamar(c, "registrar_gasto", valor=1, descricao="x", categoria="y")
        v = await _chamar(c, "vincular_nota", tipo="gasto", id=g["id"], caminho="00-inbox/x.md")
        await _chamar(c, "desfazer_registro", tipo="gasto", id=g["id"])
        with pytest.raises(ToolError, match=f"O gasto {g['id']} está desfeito; o vínculo não muda"):
            await _chamar(c, "desfazer_registro", tipo="vinculo", id=v["vinculo"])
    with Session(create_engine(url)) as s:
        assert s.get(Gasto, g["id"]).nota_vault == "00-inbox/x.md"  # desfazer o gasto não mexe na nota


# ---------------- Migração 0004 ----------------

def _colunas(engine, tabela) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(tabela)}


def test_migracao_0004_sobe_desce_sem_apagar_e_recusa_com_valor(tmp_path):
    # SQLite não tem now(), o padrão de criado_em na 0001: os INSERTs mandam o valor.
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "0003")
    engine = create_engine(url)
    with engine.begin() as cx:
        cx.execute(text("INSERT INTO gastos (data, valor, descricao, categoria, origem, criado_em, desfeito) "
                        "VALUES ('2026-10-15', 10, 'Livro', 'estudo', 'manual', CURRENT_TIMESTAMP, 0)"))
        cx.execute(text("INSERT INTO atividades (momento, descricao, criado_em, desfeito) "
                        "VALUES (CURRENT_TIMESTAMP, 'Estudei', CURRENT_TIMESTAMP, 0)"))

    _alembic(url, "upgrade", "head")
    engine.dispose()
    for tabela in ("gastos", "ponto", "atividades"):
        assert "nota_vault" in _colunas(engine, tabela)
    with engine.begin() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
        # Nenhuma linha mudou na subida.
        assert cx.execute(text("SELECT descricao, valor, nota_vault FROM gastos")).all() == [("Livro", 10, None)]
        cx.execute(text("UPDATE atividades SET nota_vault = '00-inbox/estudo.md'"))

    # Com valor, a descida é recusada e nada muda.
    with pytest.raises(subprocess.CalledProcessError) as erro:
        _alembic(url, "downgrade", "0003")
    assert "Downgrade da 0004 recusado" in erro.value.stderr.decode()
    assert "atividades: 1" in erro.value.stderr.decode()
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
        assert cx.execute(text("SELECT nota_vault FROM atividades")).scalar() == "00-inbox/estudo.md"

    # Sem valor, desce sem perder as linhas.
    with engine.begin() as cx:
        cx.execute(text("UPDATE atividades SET nota_vault = NULL"))  # só no banco de teste
    _alembic(url, "downgrade", "0003")
    engine.dispose()
    for tabela in ("gastos", "ponto", "atividades"):
        assert "nota_vault" not in _colunas(engine, tabela)
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        assert cx.execute(text("SELECT descricao FROM gastos")).all() == [("Livro",)]
        assert cx.execute(text("SELECT descricao FROM atividades")).all() == [("Estudei",)]

    _alembic(url, "upgrade", "head")
    engine.dispose()
    assert "nota_vault" in _colunas(engine, "gastos")


def test_migracao_0004_so_adiciona_coluna():
    """SQL do Postgres gerado pela 0004 (modo --sql, sem banco): só ADD COLUMN; GRANTs e dados intactos."""
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0003:0004", "--sql"], cwd=SERVIDOR, check=True,
                       capture_output=True, text=True,
                       env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})
    sql = [linha.strip().rstrip(";") for linha in r.stdout.splitlines()]
    mudancas = [linha for linha in sql if linha.startswith(("ALTER", "CREATE", "DROP", "GRANT", "REVOKE", "UPDATE",
                                                            "DELETE", "INSERT"))]
    assert mudancas == [
        "ALTER TABLE gastos ADD COLUMN nota_vault VARCHAR(300)",
        "ALTER TABLE ponto ADD COLUMN nota_vault VARCHAR(300)",
        "ALTER TABLE atividades ADD COLUMN nota_vault VARCHAR(300)",
        "UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003'",
    ]


def test_migracao_0004_desce_offline_e_recusada():
    """Em modo --sql não há banco para contar os vínculos: a descida é recusada, não gera DROP às cegas."""
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0004:0003", "--sql"], cwd=SERVIDOR,
                       capture_output=True, text=True,
                       env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})
    assert r.returncode != 0
    assert "Downgrade da 0004 não roda em modo --sql" in r.stderr
    assert "DROP COLUMN" not in r.stdout


async def test_descricao_de_nota_vault_aponta_a_nota_do_dia(app):
    """Ficha 3 (2026-10-18): o exemplo de caminho é a nota do dia em 50-diario, não a inbox."""
    async with Client(app) as c:
        ferramentas = {t.name: t for t in await c.list_tools()}
    for nome in ("registrar_gasto", "registrar_ponto", "registrar_atividade"):
        descricao = str(ferramentas[nome].input_schema["properties"]["nota_vault"])
        assert "50-diario/2026/2026-10-20.md" in descricao and "00-inbox" not in descricao
