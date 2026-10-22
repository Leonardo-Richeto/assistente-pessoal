"""Sessões do Claude Code no banco (Sprint 2b, Passo 11; ficha 5, regra 9 e extensão de 2026-10-22).

Importador (`python -m assistente.sessoes importar`), `consultar_sessoes` e a migração 0006 em SQLite. Os GRANTs no
Postgres estão em test_sessoes_pg.py; o envio (`ferramentas/sessoes/enviar.py`) ponta a ponta, em
ferramentas/sessoes/tests/test_sessoes_enviar.py.
"""

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastmcp import Client
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from assistente import sessoes
from assistente.modelos import Auditoria, Sessao
from test_registro import SERVIDOR, _alembic, app, recebidas, url  # noqa: F401 (fixtures)

AGORA = datetime.now(timezone.utc).replace(microsecond=0)


def resumo(sessao="aaaaaaaa-0001", fim=None, **extra) -> dict:
    """Resumo no formato do hook (resumo.py, versao_resumo 2)."""
    fim = fim or AGORA - timedelta(hours=1)
    base = {
        "sessao": sessao, "projeto": "assistente-pessoal", "raiz": "/Users/leo/Projetos/assistente-pessoal",
        "maquina": "macbookair", "inicio": (fim - timedelta(minutes=47)).isoformat(), "fim": fim.isoformat(),
        "duracao_min": 47, "titulo": "Arruma o deploy", "arquivos": ["servidor/app.py", "CONTEXTO.md"],
        "comandos": ["git status", "uv run pytest"], "commits": [{"id": "1a2b3c4", "mensagem": "Corrige deploy"}],
        "passagem": True, "motivo_fim": "prompt_input_exit", "versao_resumo": 2,
    }
    base.update(extra)
    return base


def _jsonl(*itens) -> io.BytesIO:
    return io.BytesIO(b"".join((i if isinstance(i, bytes) else json.dumps(i).encode()) + b"\n" for i in itens))


def _importar(url, *itens) -> dict:
    engine = create_engine(url)
    try:
        return sessoes.importar(_jsonl(*itens), engine)
    finally:
        engine.dispose()


def _sessoes(url) -> list[Sessao]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Sessao).order_by(Sessao.id)))


def _auditoria(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


# ---------------- Importar ----------------

def test_resumo_valido_entra_com_auditoria_unica(url):
    r = _importar(url, resumo("aaaaaaaa-0001"), resumo("bbbbbbbb-0002", maquina="pc-trabalho", parcial=True))
    assert r == {"aceitas": ["aaaaaaaa-0001", "bbbbbbbb-0002"], "repetidas": [], "recusadas": []}
    a, b = _sessoes(url)
    assert (a.sessao, a.projeto, a.maquina, a.duracao_min, a.titulo, a.passagem, a.parcial, a.motivo_fim,
            a.versao_resumo) == ("aaaaaaaa-0001", "assistente-pessoal", "macbookair", 47, "Arruma o deploy", True,
                                 False, "prompt_input_exit", 2)
    assert a.arquivos == ["servidor/app.py", "CONTEXTO.md"] and a.comandos == ["git status", "uv run pytest"]
    assert a.commits == [{"id": "1a2b3c4", "mensagem": "Corrige deploy"}]
    assert a.fim.replace(tzinfo=timezone.utc) == AGORA - timedelta(hours=1)  # SQLite: gravado em UTC, sem fuso
    assert a.recebido_em is not None and b.parcial is True
    [linha] = _auditoria(url)
    assert (linha.ferramenta, linha.tabela, linha.registro_id, linha.acao, linha.autor) == (
        "sessoes_importar", "sessoes", None, "criar", None)
    assert linha.dados == {"quantidade": 2, "repetidas": 0, "recusadas": 0, "maquinas": ["macbookair", "pc-trabalho"]}


def test_data_com_outro_fuso_vira_utc(url):
    fim = datetime(2026, 10, 20, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
    _importar(url, resumo(fim=fim, inicio="2026-10-20T12:00:00Z"))
    [s] = _sessoes(url)
    assert (s.inicio, s.fim) == (datetime(2026, 10, 20, 12, 0), datetime(2026, 10, 20, 13, 0))


def test_repetida_nao_entra_e_conta(url):
    primeiro = _importar(url, resumo())
    # De novo a mesma (sessao, fim), mais a retomada (outro fim) e a mesma repetida dentro da entrada.
    retomada = resumo(fim=AGORA, titulo="retomada")
    segundo = _importar(url, resumo(), retomada, retomada)
    assert primeiro["aceitas"] == ["aaaaaaaa-0001"]
    assert segundo == {"aceitas": ["aaaaaaaa-0001"], "repetidas": ["aaaaaaaa-0001", "aaaaaaaa-0001"], "recusadas": []}
    assert [s.titulo for s in _sessoes(url)] == ["Arruma o deploy", "retomada"]
    assert [a.dados for a in _auditoria(url)] == [
        {"quantidade": 1, "repetidas": 0, "recusadas": 0, "maquinas": ["macbookair"]},
        {"quantidade": 1, "repetidas": 2, "recusadas": 0, "maquinas": ["macbookair"]}]


def test_mesmo_fim_com_outra_grafia_e_repetido(url):
    """O índice compara o instante: '…-03:00' e o mesmo instante em UTC são a mesma linha."""
    fim = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
    _importar(url, resumo(fim=fim, inicio=None))
    r = _importar(url, resumo(fim=fim, inicio=None) | {"fim": "2026-10-20T10:00:00-03:00"})
    assert r["repetidas"] == ["aaaaaaaa-0001"] and len(_sessoes(url)) == 1


def test_indice_unico_segura_a_mesma_sessao_e_fim(url):
    engine = create_engine(url)
    linha = sessoes.validar(resumo())
    with Session(engine) as s, s.begin():
        s.add(Sessao(**linha))
    with pytest.raises(IntegrityError), Session(engine) as s, s.begin():
        s.add(Sessao(**linha))


@pytest.mark.parametrize("mudanca, motivo", [
    ({"sessao": "curto"}, "sessao: id inválido"),
    ({"sessao": "a" * 81}, "sessao: id inválido"),
    ({"sessao": "aaaaaaaa/../x"}, "sessao: id inválido"),
    ({"sessao": "aaaaaaaa-0001\n"}, "sessao: id inválido"),
    ({"sessao": 12345678}, "sessao: id inválido"),
    ({"fim": "2026-10-20T10:00:00"}, "fim: data sem fuso"),
    ({"fim": "ontem"}, "fim: não é data ISO"),
    ({"fim": None}, "fim: não é data ISO"),
    ({"inicio": 1729420000}, "inicio: não é data ISO"),
    ({"fim": "1970-01-01T00:00:00+00:00", "inicio": None}, "fim: ano fora"),
    ({"inicio": "2026-10-21T10:00:00+00:00", "fim": "2026-10-20T10:00:00+00:00"}, "inicio: depois do fim"),
    ({"duracao_min": "47"}, "duracao_min: não é inteiro"),
    ({"duracao_min": True}, "duracao_min: não é inteiro"),
    ({"duracao_min": -1}, "duracao_min: não é inteiro"),
    ({"duracao_min": 4.5}, "duracao_min: não é inteiro"),
    ({"titulo": ["x"]}, "titulo: não é texto"),
    ({"projeto": ""}, "projeto: vazio"),
    ({"maquina": "   "}, "maquina: vazio"),
    ({"arquivos": "a.py"}, "arquivos: não é lista"),
    ({"arquivos": ["a.py", {"caminho": "b.py"}]}, "arquivos: não é texto"),
    ({"comandos": [1]}, "comandos: não é texto"),
    ({"commits": ["1a2b3c4"]}, "commits: item não é objeto"),
    ({"commits": [{"id": "não-hex", "mensagem": "x"}]}, "commits: id inválido"),
    ({"commits": [{"id": "1a2b3c4"}]}, "commits.mensagem: não é texto"),
    ({"passagem": "true"}, "passagem: não é true ou false"),
    ({"parcial": 1}, "parcial: não é true ou false"),
    ({"versao_resumo": 1}, "versao_resumo: desconhecida"),
    ({"versao_resumo": "2"}, "versao_resumo: desconhecida"),
])
def test_recusa_por_tipo_tamanho_id_e_data(url, mudanca, motivo):
    r = _importar(url, resumo("bbbbbbbb-0002"), resumo() | mudanca)
    assert r["aceitas"] == ["bbbbbbbb-0002"]  # a válida segue
    [recusa] = r["recusadas"]
    assert recusa["linha"] == 2 and recusa["motivo"].startswith(motivo), recusa
    assert [s.sessao for s in _sessoes(url)] == ["bbbbbbbb-0002"]
    assert _auditoria(url)[0].dados["recusadas"] == 1


def test_motivo_nao_repete_o_valor(url):
    segredo = "ghp_" + "x" * 36
    r = _importar(url, resumo(sessao=segredo + "!"), resumo() | {"fim": segredo})
    assert len(r["recusadas"]) == 2 and segredo not in json.dumps(r)


@pytest.mark.parametrize("linha, motivo", [
    (b"{nao e json", "não é JSON válido"),
    (b"\xff\xfe{}", "não é JSON válido"),
    (b"[1, 2]", "não é um objeto JSON"),
    (b"\"texto\"", "não é um objeto JSON"),
    (b"[" * 100_000 + b"]" * 100_000, "não é JSON válido"),
])
def test_linha_que_nao_e_resumo(url, linha, motivo):
    r = _importar(url, linha, resumo())
    assert r["aceitas"] == ["aaaaaaaa-0001"]
    assert [x["linha"] for x in r["recusadas"]] == [1] and r["recusadas"][0]["motivo"].startswith(motivo)


def test_falta_campo(url):
    incompleto = resumo()
    del incompleto["fim"], incompleto["titulo"]
    r = _importar(url, incompleto)
    assert r["recusadas"] == [{"linha": 1, "motivo": "faltam campos: fim, titulo"}]


def test_campo_extra_e_descartado_e_parcial_e_opcional(url):
    r = _importar(url, resumo(conteudo="texto da conversa", segredo="x", __class__="y"))
    assert r["aceitas"] == ["aaaaaaaa-0001"]
    assert _sessoes(url)[0].parcial is False
    limpo = sessoes.validar(resumo(conteudo="x", commits=[{"id": "1a2b3c4", "mensagem": "m", "autor": "eu"}]))
    assert "conteudo" not in limpo and limpo["commits"] == [{"id": "1a2b3c4", "mensagem": "m"}]


def test_textos_e_listas_cortados(url):
    r = _importar(url, resumo(
        projeto="p" * 500, raiz="/r" * 500, maquina="m" * 100, titulo="t" * 1000, motivo_fim="f" * 100,
        arquivos=[f"a{i}.py" for i in range(80)], comandos=["c" * 1000] * 40,
        commits=[{"id": f"{i:07x}", "mensagem": "x" * 500} for i in range(30)]))
    assert r["aceitas"] == ["aaaaaaaa-0001"]
    [s] = _sessoes(url)
    assert (len(s.projeto), len(s.raiz), len(s.maquina), len(s.titulo), len(s.motivo_fim)) == (120, 300, 60, 200, 40)
    assert len(s.arquivos) == 50 and s.arquivos[-1] == "a49.py"
    assert len(s.comandos) == 30 and {len(c) for c in s.comandos} == {300}
    assert len(s.commits) == 20 and {len(c["mensagem"]) for c in s.commits} == {200}


def test_controle_e_surrogate_viram_texto_seguro(url):
    """NUL (o Postgres recusa) e surrogate solto (não vira UTF-8) não derrubam a transação inteira."""
    linha = json.dumps(resumo(titulo="a\x00b\nc \ud83d fim", arquivos=["x\ty.py"])).encode()
    assert b"\\ud83d" in linha
    assert _importar(url, linha)["aceitas"] == ["aaaaaaaa-0001"]
    [s] = _sessoes(url)
    assert s.titulo == "a b c ? fim" and s.arquivos == ["x y.py"]


def test_limite_de_linhas(url, monkeypatch):
    monkeypatch.setattr(sessoes, "MAX_LINHAS", 3)
    itens = [resumo(f"aaaaaaaa-{i:04d}") for i in range(5)]
    r = _importar(url, itens[0], b"", itens[1], itens[2], itens[3], itens[4])  # linha vazia não conta
    assert r["aceitas"] == ["aaaaaaaa-0000", "aaaaaaaa-0001", "aaaaaaaa-0002"]
    assert r["recusadas"] == [{"linha": 5, "motivo": "passou de 3 linhas por execução; esta e as seguintes ficam "
                                                     "para a próxima"}]


def test_limite_de_bytes(url, monkeypatch):
    linha = json.dumps(resumo()).encode()
    monkeypatch.setattr(sessoes, "MAX_BYTES", len(linha) * 2 + 10)  # cabem 2 linhas e um pedaço da terceira
    itens = [resumo(f"aaaaaaaa-{i:04d}") for i in range(4)]
    r = _importar(url, *itens)
    assert r["aceitas"] == ["aaaaaaaa-0000", "aaaaaaaa-0001"]
    assert [x["linha"] for x in r["recusadas"]] == [3] and "MB por execução" in r["recusadas"][0]["motivo"]


def test_limites_padrao():
    assert (sessoes.MAX_LINHAS, sessoes.MAX_BYTES) == (2000, 2 * 1024 * 1024)
    assert {c: n for c, (n, _) in sessoes.LISTAS.items()} | {"commits": sessoes.MAX_COMMITS} == {
        "arquivos": 50, "comandos": 30, "commits": 20}


def test_entrada_vazia_grava_so_a_auditoria(url):
    assert _importar(url) == {"aceitas": [], "repetidas": [], "recusadas": []}
    assert _sessoes(url) == [] and [a.dados["quantidade"] for a in _auditoria(url)] == [0]


# ---------------- Linha de comando ----------------

def _cli(entrada: bytes, env: dict) -> subprocess.CompletedProcess:
    """Roda o importador como o i7 roda (subprocesso). Valor None tira a variável do ambiente do filho."""
    ambiente = {k: v for k, v in {**os.environ, **env}.items() if v is not None}
    return subprocess.run([sys.executable, "-m", "assistente.sessoes", "importar"], cwd=SERVIDOR, input=entrada,
                          capture_output=True, env=ambiente)


def test_linha_de_comando_imprime_json_e_sai_com_0(url):
    entrada = b"".join(json.dumps(x).encode() + b"\n" for x in (resumo(), resumo(), {"sessao": "x"}))
    r = _cli(entrada, {"DATABASE_URL_ESCRITA": url})
    assert (r.returncode, r.stderr) == (0, b"")
    saida = json.loads(r.stdout)
    assert (saida["aceitas"], saida["repetidas"]) == (["aaaaaaaa-0001"], ["aaaaaaaa-0001"])
    assert [x["linha"] for x in saida["recusadas"]] == [3] and saida["recusadas"][0]["motivo"].startswith("faltam")
    assert r.stdout.isascii()


@pytest.mark.parametrize("valor", [None, "sqlite:////pasta/que/nao/existe/x.db"])
def test_linha_de_comando_sem_banco_sai_com_2(valor):
    r = _cli(json.dumps(resumo()).encode() + b"\n", {"DATABASE_URL_ESCRITA": valor})
    assert r.returncode == 2 and r.stdout == b""
    assert r.stderr.decode().startswith("sessoes: ") and "pasta/que/nao" not in r.stderr.decode()


def test_linha_de_comando_sem_tabela_nao_grava_nada(tmp_path):
    """Banco sem a 0006: falha a transação inteira, nada entra (nem a auditoria)."""
    url = f"sqlite:///{tmp_path / 'velho.db'}"
    _alembic(url, "upgrade", "0005")
    r = _cli(json.dumps(resumo()).encode() + b"\n", {"DATABASE_URL_ESCRITA": url})
    assert r.returncode == 2 and r.stdout == b""
    with create_engine(url).connect() as cx:
        assert cx.execute(text("SELECT count(*) FROM auditoria")).scalar() == 0


# ---------------- consultar_sessoes ----------------

async def _consultar(app, **args) -> list[dict]:
    async with Client(app) as c:
        return (await c.call_tool("consultar_sessoes", args)).data


async def test_consultar_devolve_a_mais_nova_de_cada_sessao(app, url):
    _importar(url,
              resumo("aaaaaaaa-0001", fim=AGORA - timedelta(hours=5), titulo="primeira parte", passagem=False),
              resumo("aaaaaaaa-0001", fim=AGORA - timedelta(hours=1), titulo="retomada", passagem=True),
              resumo("bbbbbbbb-0002", fim=AGORA - timedelta(hours=3), titulo="outra",
                     arquivos=[f"a{i}.py" for i in range(20)]))
    r = await _consultar(app)
    assert [(x["sessao"], x["titulo"]) for x in r] == [("aaaaaaaa-0001", "retomada"), ("bbbbbbbb-0002", "outra")]
    assert set(r[0]) == {"sessao", "projeto", "maquina", "inicio", "fim", "duracao_min", "titulo", "passagem",
                         "arquivos", "commits"}  # sem comandos
    assert len(r[1]["arquivos"]) == 10
    assert r[0]["commits"] == [{"id": "1a2b3c4", "mensagem": "Corrige deploy"}]
    # Fuso local: o fim volta em America/Sao_Paulo.
    assert r[0]["fim"].endswith("-03:00")
    assert datetime.fromisoformat(r[0]["fim"]) == AGORA - timedelta(hours=1)
    assert datetime.fromisoformat(r[0]["inicio"]) == AGORA - timedelta(hours=1, minutes=47)
    # Leitura: nenhuma linha nova na auditoria.
    assert len(_auditoria(url)) == 1


async def test_consultar_filtros(app, url):
    _importar(url,
              resumo("aaaaaaaa-0001", projeto="Assistente-Pessoal", maquina="macbookair", passagem=True),
              resumo("bbbbbbbb-0002", fim=AGORA - timedelta(hours=2), projeto="loja_virtual", maquina="pc-trabalho",
                     passagem=False),
              resumo("cccccccc-0003", fim=AGORA - timedelta(hours=3), projeto="lojaXvirtual", maquina="macbookair",
                     passagem=False))

    async def ids(**args):
        return [x["sessao"] for x in await _consultar(app, **args)]

    assert await ids(projeto="assistente") == ["aaaaaaaa-0001"]
    assert await ids(projeto="  PESSOAL ") == ["aaaaaaaa-0001"]
    assert await ids(projeto="loja_") == ["bbbbbbbb-0002"]  # _ é literal, não coringa
    assert await ids(projeto="%") == []
    assert await ids(maquina="MacBookAir") == ["aaaaaaaa-0001", "cccccccc-0003"]
    assert await ids(maquina="pc") == []  # máquina é o nome inteiro
    assert await ids(sem_passagem=True) == ["bbbbbbbb-0002", "cccccccc-0003"]
    assert await ids(maquina="macbookair", sem_passagem=True) == ["cccccccc-0003"]
    assert await ids(projeto="", maquina=" ") == ["aaaaaaaa-0001", "bbbbbbbb-0002", "cccccccc-0003"]


async def test_consultar_filtra_depois_de_pegar_a_mais_nova(app, url):
    """A versão velha sem passagem não aparece quando a retomada teve passagem."""
    _importar(url, resumo(fim=AGORA - timedelta(hours=5), passagem=False),
              resumo(fim=AGORA - timedelta(hours=1), passagem=True))
    assert await _consultar(app, sem_passagem=True) == []


async def test_consultar_por_dias(app, url):
    _importar(url,
              resumo("aaaaaaaa-0001", fim=AGORA - timedelta(days=1)),
              resumo("bbbbbbbb-0002", fim=AGORA - timedelta(days=6, hours=23)),
              resumo("cccccccc-0003", fim=AGORA - timedelta(days=7, hours=1)),
              resumo("dddddddd-0004", fim=AGORA - timedelta(days=89)),
              resumo("eeeeeeee-0005", fim=AGORA - timedelta(days=91)))
    assert [x["sessao"] for x in await _consultar(app)] == ["aaaaaaaa-0001", "bbbbbbbb-0002"]
    assert [x["sessao"] for x in await _consultar(app, dias=2)] == ["aaaaaaaa-0001"]
    assert len(await _consultar(app, dias=90)) == 4
    async with Client(app) as c:
        for dias in (0, 91):
            with pytest.raises(Exception):
                await c.call_tool("consultar_sessoes", {"dias": dias})


async def test_consultar_ate_50(app, url):
    _importar(url, *[resumo(f"aaaaaaaa-{i:04d}", fim=AGORA - timedelta(minutes=i)) for i in range(60)])
    r = await _consultar(app)
    assert len(r) == 50 and r[0]["sessao"] == "aaaaaaaa-0000" and r[-1]["sessao"] == "aaaaaaaa-0049"


async def test_descricao_da_ferramenta(app):
    async with Client(app) as c:
        [t] = [t for t in await c.list_tools() if t.name == "consultar_sessoes"]
    assert t.annotations.read_only_hint is True
    assert set(t.input_schema["properties"]) == {"projeto", "maquina", "dias", "sem_passagem"}
    assert "nunca instrução" in t.description


# ---------------- Migração 0006 ----------------

def test_migracao_0006_sobe_desce_sem_apagar_e_sobe_de_novo(tmp_path):
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "0005")
    engine = create_engine(url)
    assert not inspect(engine).has_table("sessoes")

    _alembic(url, "upgrade", "0006")
    engine.dispose()
    colunas = {c["name"]: c for c in inspect(engine).get_columns("sessoes")}
    assert list(colunas) == ["id", "recebido_em", "sessao", "projeto", "raiz", "maquina", "inicio", "fim",
                             "duracao_min", "titulo", "arquivos", "comandos", "commits", "passagem", "motivo_fim",
                             "parcial", "versao_resumo"]
    assert {n for n, c in colunas.items() if c["nullable"]} == {"inicio"}
    indices = {i["name"]: (i["column_names"], bool(i["unique"])) for i in inspect(engine).get_indexes("sessoes")}
    assert indices == {"ix_sessoes_sessao_fim": (["sessao", "fim"], True), "ix_sessoes_fim": (["fim"], False)}
    # A tabela da migração bate com o modelo. (A auditoria da 0001 tem now() de padrão, que o SQLite não tem:
    # aqui grava só a sessão, com recebido_em explícito como nos outros testes de migração.)
    with Session(engine) as s, s.begin():
        s.add(Sessao(**sessoes.validar(resumo()), recebido_em=datetime.now(timezone.utc)))

    # Descer não apaga a tabela nem as sessões.
    _alembic(url, "downgrade", "0005")
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
        assert cx.execute(text("SELECT sessao FROM sessoes")).scalars().all() == ["aaaaaaaa-0001"]

    # Subir de novo reaproveita a tabela que ficou.
    _alembic(url, "upgrade", "0006")
    engine.dispose()
    with engine.connect() as cx:
        assert cx.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0006"
        assert cx.execute(text("SELECT count(*) FROM sessoes")).scalar() == 1


def _sql_offline(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args, "--sql"], cwd=SERVIDOR, capture_output=True,
                          text=True, env={**os.environ, "DATABASE_URL_MIGRACAO": "postgresql+psycopg://x@localhost/x"})


def test_migracao_0006_grants_no_postgres():
    """SQL do Postgres gerado pela 0006 (modo --sql, sem banco): só INSERT e SELECT para a escrita."""
    r = _sql_offline("upgrade", "0005:0006")
    assert r.returncode == 0, r.stderr
    sql = [linha.strip().rstrip(";") for linha in r.stdout.splitlines()]
    assert [linha for linha in sql if linha.startswith(("GRANT", "REVOKE"))] == [
        "REVOKE ALL ON TABLE sessoes FROM assistente_escrita, assistente_leitura",
        "REVOKE ALL ON SEQUENCE sessoes_id_seq FROM assistente_escrita, assistente_leitura",
        "GRANT SELECT, INSERT ON TABLE sessoes TO assistente_escrita",
        "GRANT USAGE, SELECT ON SEQUENCE sessoes_id_seq TO assistente_escrita",
        "GRANT SELECT ON TABLE sessoes TO assistente_leitura",
    ]
    assert "CREATE UNIQUE INDEX ix_sessoes_sessao_fim ON sessoes (sessao, fim)" in sql
    assert not [linha for linha in sql if linha.startswith(("DROP", "DELETE", "ALTER"))]


def test_migracao_0006_desce_offline_sem_apagar():
    r = _sql_offline("downgrade", "0006:0005")
    assert r.returncode == 0, r.stderr
    assert "DROP" not in r.stdout
    assert "UPDATE alembic_version SET version_num='0005'" in r.stdout
