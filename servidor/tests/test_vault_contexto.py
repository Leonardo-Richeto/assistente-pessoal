"""contexto_inicial (Passo 7 da Sprint 2b, item 2b.6): perfil, trabalho em andamento, nota do dia, marcas.

Vault sintético copiado para tmp_path; o dia é fixado trocando vault._agora.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from fastmcp import Client
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import servidor, vault
from assistente.config import Config
from assistente.modelos import Base, Chamada
from test_bloqueadas import _proxy_falso

ORIGINAL = Path(__file__).parent / "fixtures" / "vault"
CORTE = "…(cortado; leia com ler_nota)"
DIA_COM_NOTA = datetime(2026, 10, 20, 9, 5, tzinfo=vault.FUSO)


@pytest.fixture
def raiz(tmp_path) -> Path:
    destino = tmp_path / "vault"
    shutil.copytree(ORIGINAL, destino)
    return destino


@pytest.fixture(autouse=True)
def dia(monkeypatch):
    monkeypatch.setattr(vault, "_agora", lambda: DIA_COM_NOTA)


def _app(raiz: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(servidor, "create_proxy", _proxy_falso)
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(raiz))
    return servidor.criar_app(cfg), url


async def _contexto(app) -> dict:
    async with Client(app) as c:
        return (await c.call_tool("contexto_inicial", {})).data


def _escrever(raiz: Path, caminho: str, texto: str) -> None:
    p = raiz / caminho
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")


async def test_tudo_presente(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    r = await _contexto(app)
    assert r["hoje"] == "2026-10-20 09:05"
    assert r["perfil"].splitlines()[0] == "# Perfil do Leonardo"  # sem o frontmatter
    assert len(r["perfil"].splitlines()) == 5
    assert "Prefere respostas curtas" in r["perfil"]
    assert r["trabalho_em_andamento"].startswith("- Horta comunitária: etapa de manutenção")
    assert "plano-de-estudos" in r["trabalho_em_andamento"]
    assert "Trabalho em andamento" not in r["trabalho_em_andamento"]
    assert "Tarefas por máquina" not in r["trabalho_em_andamento"]
    dia_nota = r["nota_do_dia"]
    assert dia_nota["caminho"] == "50-diario/2026/2026-10-20.md" and dia_nota["existe"] is True
    assert dia_nota["conteudo"] and not dia_nota["conteudo"].startswith("---")
    assert r["desatualizadas"] == 0
    assert "cortado" not in r
    assert len(json.dumps(r, ensure_ascii=False)) <= 6000


async def test_cada_parte_ausente(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    (raiz / vault.PERFIL_CAMINHO).unlink()
    assert (await _contexto(app))["perfil"] is None
    (raiz / vault.ONDE_PAREI_CAMINHO).unlink()
    assert (await _contexto(app))["trabalho_em_andamento"] is None
    (raiz / "50-diario/2026/2026-10-20.md").unlink()
    r = await _contexto(app)
    assert r["nota_do_dia"] == {"caminho": "50-diario/2026/2026-10-20.md", "existe": False}
    assert r["desatualizadas"] == 0 and r["hoje"]


async def test_onde_parei_sem_a_secao_e_secao_vazia(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, vault.ONDE_PAREI_CAMINHO, "# Onde parei\n\n## Tarefas por máquina\n\n- x\n")
    assert (await _contexto(app))["trabalho_em_andamento"] is None
    _escrever(raiz, vault.ONDE_PAREI_CAMINHO, "## Trabalho em andamento\n\n## Outra\n\n- y\n")
    assert (await _contexto(app))["trabalho_em_andamento"] == ""


async def test_secao_vai_ate_o_proximo_titulo(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, vault.ONDE_PAREI_CAMINHO,
              "## A\n\n- a\n\n## Trabalho em andamento\n\n- b\n### sub\n- c\n\n## Depois\n\n- d\n")
    assert (await _contexto(app))["trabalho_em_andamento"] == "- b\n### sub\n- c"


async def test_nota_do_dia_de_hoje_no_fuso_de_sp(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    monkeypatch.setattr(vault, "_agora", lambda: datetime(2026, 10, 23, 23, 30, tzinfo=vault.FUSO))
    r = await _contexto(app)
    assert r["nota_do_dia"] == {"caminho": "50-diario/2026/2026-10-23.md", "existe": False}
    _escrever(raiz, "50-diario/2026/2026-10-23.md", "---\ntitulo: x\n---\n\nDia 23: reunião às 10h.\n")
    r = await _contexto(app)
    assert r["nota_do_dia"]["conteudo"] == "Dia 23: reunião às 10h."
    assert r["hoje"] == "2026-10-23 23:30"


def test_agora_usa_o_fuso_de_sao_paulo():
    assert str(vault._agora().tzinfo) == "America/Sao_Paulo"


async def test_cortes_por_parte_e_teto(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, vault.PERFIL_CAMINHO, "\n".join("p" * 400 for _ in range(30)))
    # (12 linhas de 400 = 4.800 caracteres, cortados em 1.500)
    _escrever(raiz, vault.ONDE_PAREI_CAMINHO, "## Trabalho em andamento\n\n" + "t" * 100_000 + "\n")
    _escrever(raiz, "50-diario/2026/2026-10-20.md", "n" * 100_000)
    r = await _contexto(app)
    assert len(r["perfil"]) == 1500 and r["perfil"].endswith(CORTE)
    assert len(r["trabalho_em_andamento"]) == 2500 and r["trabalho_em_andamento"].endswith(CORTE)
    # Os três tetos somam 5.800; com as chaves do JSON a resposta passa de 6.000 e a nota do dia perde o excesso.
    assert 1700 < len(r["nota_do_dia"]["conteudo"]) <= 1800 and r["nota_do_dia"]["conteudo"].endswith(CORTE)
    assert r["cortado"] == ["perfil", "trabalho_em_andamento", "nota_do_dia"]
    assert len(json.dumps(r, ensure_ascii=False)) <= 6000


async def test_sem_corte_nao_traz_a_chave(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, "50-diario/2026/2026-10-20.md", "n" * 1800)
    r = await _contexto(app)
    assert "cortado" not in r and len(r["nota_do_dia"]["conteudo"]) == 1800


async def test_teto_vale_com_texto_que_o_json_escapa(raiz, tmp_path, monkeypatch):
    """Aspas e quebras de linha incham o JSON; o teto de 6.000 vale para a resposta inteira."""
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, vault.PERFIL_CAMINHO, "\n".join('"' * 200 for _ in range(12)))
    _escrever(raiz, vault.ONDE_PAREI_CAMINHO, "## Trabalho em andamento\n" + '"\n' * 50_000)
    _escrever(raiz, "50-diario/2026/2026-10-20.md", '"\n' * 50_000)
    r = await _contexto(app)
    assert len(json.dumps(r, ensure_ascii=False)) <= 6000
    assert r["cortado"]


async def test_arquivo_fora_de_utf8_e_lido_com_substituicao(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    (raiz / "50-diario/2026/2026-10-20.md").write_bytes(b"oi \xff\xfe fim")
    r = await _contexto(app)
    assert r["nota_do_dia"]["conteudo"] == "oi �� fim"


async def test_conta_so_marcas_em_vigor(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    async with Client(app) as c:
        a = (await c.call_tool("marcar_desatualizada", {"caminho": "20-areas/perfil-do-leonardo.md", "motivo": "velha"})).data
        await c.call_tool("marcar_desatualizada", {"caminho": "00-inbox/onde-parei.md", "motivo": "errada"})
        assert (await c.call_tool("contexto_inicial", {})).data["desatualizadas"] == 2
        await c.call_tool("desfazer_registro", {"tipo": "desatualizada", "id": a["id"]})
        assert (await c.call_tool("contexto_inicial", {})).data["desatualizadas"] == 1


async def test_banco_quebrado_vira_null_com_aviso(raiz, tmp_path, monkeypatch, caplog):
    app, url = _app(raiz, tmp_path, monkeypatch)
    Base.metadata.tables["notas_desatualizadas"].drop(create_engine(url))
    with caplog.at_level(logging.WARNING, logger="assistente.vault"):
        r = await _contexto(app)
    assert r["desatualizadas"] is None
    assert r["perfil"] and r["trabalho_em_andamento"]
    assert any("contexto_inicial" in m.getMessage() and m.levelno == logging.WARNING for m in caplog.records)


def test_sem_banco_desatualizadas_e_null(raiz):
    r = vault._contexto(raiz, None)
    assert r["desatualizadas"] is None and r["perfil"]


async def test_registra_chamada_sem_conteudo(raiz, tmp_path, monkeypatch):
    segredo = "zz-texto-secreto-do-dia"
    _escrever(raiz, "50-diario/2026/2026-10-20.md", f"Dia\n\n{segredo}\n")
    app, url = _app(raiz, tmp_path, monkeypatch)
    r = await _contexto(app)
    assert segredo in r["nota_do_dia"]["conteudo"]
    with Session(create_engine(url)) as s:
        chamadas = s.scalars(select(Chamada).where(Chamada.ferramenta == "contexto_inicial")).all()
        assert len(chamadas) == 1 and chamadas[0].resultado == "ok"
        assert segredo not in repr([c.__dict__ for c in s.scalars(select(Chamada)).all()])


async def test_perfil_so_as_12_primeiras_linhas_depois_do_frontmatter(raiz, tmp_path, monkeypatch):
    app, _ = _app(raiz, tmp_path, monkeypatch)
    _escrever(raiz, vault.PERFIL_CAMINHO, "---\ntitulo: x\n---\n" + "\n".join(f"linha {i}" for i in range(1, 30)))
    assert (await _contexto(app))["perfil"].splitlines() == [f"linha {i}" for i in range(1, 13)]
