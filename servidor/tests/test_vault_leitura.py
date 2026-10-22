"""Leitura do vault (Passo 3 da Sprint 2b): caminho_seguro, ler_nota e notas_recentes.

Vault sintético copiado para tmp_path; teste que cria nota trabalha na cópia.
"""

import os
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import servidor, vault
from assistente.config import Config
from assistente.modelos import Base, Chamada
from test_bloqueadas import _proxy_falso

ORIGINAL = Path(__file__).parent / "fixtures" / "vault"
HORTA = "10-projetos/horta-comunitaria/horta-comunitaria.md"


@pytest.fixture
def raiz(tmp_path) -> Path:
    destino = tmp_path / "vault"
    shutil.copytree(ORIGINAL, destino)
    return destino


def _app(raiz: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(servidor, "create_proxy", _proxy_falso)
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(raiz))
    return servidor.criar_app(cfg), url


def _nota(raiz: Path, caminho: str, texto: str, mtime: int | None = None) -> None:
    p = raiz / caminho
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))


# ---------------- caminho_seguro ----------------

def test_caminho_seguro_aceita_nota_normal(raiz):
    assert vault.caminho_seguro(raiz, HORTA) == Path(os.path.realpath(raiz / HORTA))


@pytest.mark.parametrize("hostil", [
    "", "   ", "../fora.md", "a/../../fora.md", "/etc/passwd.md", "~/nota.md", "．．/fora.md", "a/．．/b.md",
    ".git/config", ".git/HEAD.md", ".obsidian/app.json", ".stversions/x.md", ".trash/x.md", "a/.git/x.md",
    "nota.txt", "10-projetos/horta-comunitaria", "a\\b.md",
])
def test_caminho_seguro_recusa(raiz, hostil):
    with pytest.raises(ToolError):
        vault.caminho_seguro(raiz, hostil)


def test_caminho_seguro_recusa_link_simbolico_para_fora(raiz, tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.md").write_text("fora", encoding="utf-8")
    (raiz / "link-arquivo.md").symlink_to(fora / "segredo.md")
    (raiz / "link-pasta").symlink_to(fora)
    for c in ("link-arquivo.md", "link-pasta/segredo.md"):
        with pytest.raises(ToolError, match="Caminho fora do vault"):
            vault.caminho_seguro(raiz, c)


def test_caminho_seguro_recusa_link_para_pasta_ignorada(raiz):
    (raiz / "atalho").symlink_to(raiz / ".obsidian")
    with pytest.raises(ToolError):
        vault.caminho_seguro(raiz, "atalho/app.md")


def test_versao_de_e_estavel_e_curta():
    assert vault.versao_de(b"abc") == vault.versao_de(b"abc")
    assert vault.versao_de(b"abc") != vault.versao_de(b"abd")
    assert len(vault.versao_de(b"")) == 16


# ---------------- ler_nota ----------------

async def test_ler_nota_conteudo_versao_e_relacionadas(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        ferramentas = {t.name: t for t in await c.list_tools()}
        for nome in ("ler_nota", "notas_recentes"):
            assert ferramentas[nome].annotations.read_only_hint is True
        r = (await c.call_tool("ler_nota", {"caminho": HORTA})).data
        assert set(r) >= {"caminho", "conteudo", "versao", "relacionadas"} and "cortado" not in r
        assert r["caminho"] == HORTA and "mutirão de sábado" in r["conteudo"]
        assert r["versao"] == vault.versao_de((raiz / HORTA).read_bytes())
        links = [(x["caminho"], x["relacao"]) for x in r["relacionadas"]]
        assert links[:2] == [("10-projetos/horta-comunitaria/decisao-compostagem.md", "link"),
                             ("60-planos/plano-de-estudos.md", "link")]
        # cronograma e decisao citam horta-comunitaria: decisao já é link (não repete); cronograma é backlink.
        assert ("10-projetos/horta-comunitaria/cronograma.md", "backlink") in links
        assert len(links) == len({c for c, _ in links})
        assert set(r["relacionadas"][0]) == {"caminho", "titulo", "resumo", "relacao"}
        assert r["relacionadas"][0]["resumo"].startswith("Decidimos")

        sem = (await c.call_tool("ler_nota", {"caminho": HORTA, "relacionadas": False})).data
        assert sem["relacionadas"] == []


async def test_versao_estavel_e_muda_com_o_conteudo(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        v1 = (await c.call_tool("ler_nota", {"caminho": HORTA})).data["versao"]
        assert (await c.call_tool("ler_nota", {"caminho": HORTA})).data["versao"] == v1
        (raiz / HORTA).write_text((raiz / HORTA).read_text(encoding="utf-8") + "\nMais uma linha.\n", encoding="utf-8")
        v2 = (await c.call_tool("ler_nota", {"caminho": HORTA})).data["versao"]
        assert v2 != v1 and len(v2) == 16


async def test_wikilinks_com_apelido_titulo_e_pasta(raiz, tmp_path, monkeypatch):
    _nota(raiz, "x/a.md", "# A\n\n> resumo a\n\n[[b|apelido]] [[c#secao]] [[x/d]] [[b]] [[nao-existe]] [[a]]\n")
    _nota(raiz, "x/b.md", "# B\n\n> resumo b\n")
    _nota(raiz, "x/c.md", "# C\n")
    _nota(raiz, "x/d.md", "# D\n")
    _nota(raiz, "y/e.md", "# E\n\nVeja [[a|o A]].\n")
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        r = (await c.call_tool("ler_nota", {"caminho": "x/a.md"})).data["relacionadas"]
        assert [(x["caminho"], x["relacao"]) for x in r] == [
            ("x/b.md", "link"), ("x/c.md", "link"), ("x/d.md", "link"), ("y/e.md", "backlink")]
        b = (await c.call_tool("ler_nota", {"caminho": "x/b.md"})).data["relacionadas"]
        assert [(x["caminho"], x["relacao"]) for x in b] == [("x/a.md", "backlink")]


async def test_nome_repetido_prefere_caminho_completo_ou_primeiro_alfabetico(raiz, tmp_path, monkeypatch):
    _nota(raiz, "z/dup.md", "# Z\n")
    _nota(raiz, "m/dup.md", "# M\n")
    _nota(raiz, "o/curto.md", "# O\n\n[[dup]]\n")
    _nota(raiz, "o/longo.md", "# L\n\n[[z/dup]]\n")
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        assert (await c.call_tool("ler_nota", {"caminho": "o/curto.md"})).data["relacionadas"][0]["caminho"] == "m/dup.md"
        assert (await c.call_tool("ler_nota", {"caminho": "o/longo.md"})).data["relacionadas"][0]["caminho"] == "z/dup.md"


async def test_no_maximo_dez_relacionadas_links_primeiro(raiz, tmp_path, monkeypatch):
    _nota(raiz, "h/centro.md", "# Centro\n\n" + " ".join(f"[[alvo{i:02d}]]" for i in range(8)) + "\n")
    for i in range(8):
        _nota(raiz, f"h/alvo{i:02d}.md", f"# Alvo {i}\n")
    for i in range(6):
        _nota(raiz, f"h/cita{i}.md", "# Cita\n\n[[centro]]\n")
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        r = (await c.call_tool("ler_nota", {"caminho": "h/centro.md"})).data["relacionadas"]
    assert len(r) == 10
    assert [x["relacao"] for x in r] == ["link"] * 8 + ["backlink"] * 2


async def test_nota_inexistente_e_caminho_hostil(raiz, tmp_path, monkeypatch):
    (raiz / "link.md").symlink_to(tmp_path)  # alvo fora do vault e que não é arquivo
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Nota não existe: nao/existe.md"):
            await c.call_tool("ler_nota", {"caminho": "nao/existe.md"})
        for hostil in ("../x.md", "/etc/passwd", "~/a.md", "．．/a.md", ".git/config", "a.txt", "", "link.md"):
            with pytest.raises(ToolError):
                await c.call_tool("ler_nota", {"caminho": hostil})


async def test_conteudo_grande_e_cortado(raiz, tmp_path, monkeypatch):
    _nota(raiz, "grande.md", "# G\n\n" + "a" * 250_000)
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        r = (await c.call_tool("ler_nota", {"caminho": "grande.md"})).data
    assert r["cortado"] is True and len(r["conteudo"]) == 200_000
    assert r["versao"] == vault.versao_de((raiz / "grande.md").read_bytes())


# ---------------- notas_recentes ----------------

async def test_notas_recentes_por_atualizado_com_fallback_no_mtime(raiz, tmp_path, monkeypatch):
    _nota(raiz, "r/novissima.md", "---\natualizado: 2030-01-02 10:00\n---\n# Novíssima\n", mtime=1_000_000_000)
    _nota(raiz, "r/so-data.md", "---\ntitulo: Só data\natualizado: 2030-01-01\n---\n# X\n", mtime=1_000_000_000)
    # Sem o campo: vale o mtime (2033-05-18 03:33 UTC = 00:33 em São Paulo).
    _nota(raiz, "r/sem-campo.md", "# Sem campo\n", mtime=2_000_000_000)
    _nota(raiz, "r/ruim.md", "---\natualizado: ontem\n---\n# Ruim\n", mtime=1_500_000_000)
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        r = (await c.call_tool("notas_recentes", {"n": 4, "pasta": "r"})).data
    assert [x["caminho"] for x in r] == ["r/sem-campo.md", "r/novissima.md", "r/so-data.md", "r/ruim.md"]
    assert r[0] == {"caminho": "r/sem-campo.md", "titulo": "Sem campo", "atualizado": "2033-05-18 00:33"}
    assert r[1]["atualizado"] == "2030-01-02 10:00" and r[2]["atualizado"] == "2030-01-01 00:00"
    assert len(r[3]["atualizado"]) == 16 and r[3]["atualizado"][:4] == "2017"  # do mtime (1_500_000_000)


async def test_notas_recentes_filtro_limites_e_ignorados(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        padrao = (await c.call_tool("notas_recentes", {})).data
        assert len(padrao) == 10
        caminhos = [x["caminho"] for x in padrao]
        assert not any(p.startswith((".stversions", "anexos", "templates")) or "sync-conflict" in p for p in caminhos)
        assert [x["atualizado"] for x in padrao] == sorted((x["atualizado"] for x in padrao), reverse=True)
        assert len((await c.call_tool("notas_recentes", {"n": 0})).data) == 1
        assert len((await c.call_tool("notas_recentes", {"n": -5})).data) == 1
        assert len((await c.call_tool("notas_recentes", {"n": 999})).data) <= 30
        horta = (await c.call_tool("notas_recentes", {"n": 30, "pasta": "10-projetos/"})).data
        assert horta and all(x["caminho"].startswith("10-projetos/") for x in horta)
        assert (await c.call_tool("notas_recentes", {"pasta": "10-proj"})).data == []


# ---------------- registro ----------------

async def test_ler_nota_registra_chamada_sem_conteudo(raiz, tmp_path, monkeypatch):
    segredo = "zz-texto-secreto-da-nota"
    _nota(raiz, "s/segredo.md", f"# S\n\n{segredo}\n")
    app, url = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        r = await c.call_tool("ler_nota", {"caminho": "s/segredo.md"})
        assert segredo in r.data["conteudo"]
        await c.call_tool("notas_recentes", {})
    with Session(create_engine(url)) as s:
        chamadas = s.scalars(select(Chamada).where(Chamada.ferramenta == "ler_nota")).all()
        assert len(chamadas) == 1 and chamadas[0].resultado == "ok"
        tudo = repr([(c.__dict__) for c in s.scalars(select(Chamada)).all()])
        assert segredo not in tudo
