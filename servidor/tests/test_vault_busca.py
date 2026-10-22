"""Busca no vault (Passo 1 da Sprint 2b): módulo sem FastMCP, CLI e a ferramenta `buscar_vault`.

Usa o vault sintético de fixtures/vault (nenhum dado real). Teste que mexe em arquivo trabalha numa cópia.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import registro, servidor, vault, vault_busca
from assistente.config import Config
from assistente.modelos import Auditoria, Base, Chamada
from assistente.vault_busca import IndiceVault, preparar_consulta
from test_bloqueadas import _proxy_falso

ORIGINAL = Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture
def raiz(tmp_path) -> Path:
    destino = tmp_path / "vault"
    shutil.copytree(ORIGINAL, destino)
    return destino


@pytest.fixture
def indice(raiz) -> IndiceVault:
    return IndiceVault(raiz)


def _caminhos(achados: list[dict]) -> list[str]:
    return [a["caminho"] for a in achados]


def test_resultado_tem_os_campos_combinados(indice):
    achados = indice.buscar("mutirão")
    assert achados
    assert set(achados[0]) == {"caminho", "titulo", "resumo", "pontuacao"}
    assert isinstance(achados[0]["pontuacao"], float) and achados[0]["pontuacao"] > 0
    assert "\\" not in achados[0]["caminho"]


def test_sem_acento_acha_com_acento_e_vice_versa(indice):
    com = _caminhos(indice.buscar("manutenção"))
    sem = _caminhos(indice.buscar("manutencao"))
    assert com and com == sem
    assert "10-projetos/horta-comunitaria/horta-comunitaria.md" in com
    assert _caminhos(indice.buscar("DECISAO")) == _caminhos(indice.buscar("decisão"))


def test_titulo_vence_corpo(indice):
    # "adubo" está no título de decisao-compostagem e só no corpo de cronograma.
    achados = _caminhos(indice.buscar("adubo"))
    assert achados[0] == "10-projetos/horta-comunitaria/decisao-compostagem.md"
    assert "10-projetos/horta-comunitaria/cronograma.md" in achados


def test_titulo_resumo_e_frontmatter(indice):
    nota = next(a for a in indice.buscar("perfil fictício") if a["caminho"] == "20-areas/perfil-do-leonardo.md")
    assert nota["titulo"] == "Perfil do Leonardo"
    assert nota["resumo"].startswith("Perfil fictício de teste")


def test_filtros_tipo_status_pasta(indice):
    assert _caminhos(indice.buscar("horta", tipo="decisao")) == ["10-projetos/horta-comunitaria/decisao-compostagem.md"]
    todos = _caminhos(indice.buscar("horta", limite=20))
    concluidos = _caminhos(indice.buscar("horta", status="concluido", limite=20))
    assert concluidos == ["10-projetos/horta-comunitaria/cronograma.md"] and len(todos) > 1
    na_pasta = _caminhos(indice.buscar("horta", pasta="10-projetos", limite=20))
    assert na_pasta and all(c.startswith("10-projetos/") for c in na_pasta)
    assert _caminhos(indice.buscar("horta", pasta="10-projetos/")) == _caminhos(indice.buscar("horta", pasta="10-projetos"))
    assert indice.buscar("horta", pasta="10-proj") == []  # prefixo de pasta, não de texto
    assert indice.buscar("horta", tipo="decisao", status="arquivado") == []


def test_ignorados_nao_aparecem(indice):
    achados = _caminhos(indice.buscar("compostagem", limite=20))
    assert achados
    for c in achados:
        assert not c.startswith((".obsidian", ".stversions", "anexos", "templates"))
        assert "sync-conflict" not in c
    assert indice.buscar("Syncthing") == []
    assert all("modelo.md" not in c for c in _caminhos(indice.buscar("Modelo", limite=20)))


def test_titulo_cai_para_h1_e_para_nome_do_arquivo(raiz):
    (raiz / "sem-frontmatter.md").write_text("# Cabeçalho Próprio\n\n> Resumo curto.\n\nzzcorpo\n", encoding="utf-8")
    (raiz / "so-nome-do-arquivo.md").write_text("zzsemnada\n", encoding="utf-8")
    achados = IndiceVault(raiz)
    assert achados.buscar("zzcorpo")[0]["titulo"] == "Cabeçalho Próprio"
    assert achados.buscar("zzcorpo")[0]["resumo"] == "Resumo curto."
    assert achados.buscar("zzsemnada")[0]["titulo"] == "so-nome-do-arquivo"


def test_frontmatter_com_lista_e_aspas():
    fm, corpo = vault_busca.separar_frontmatter(
        '---\r\ntitulo: "Com aspas"\r\ntags:\r\n  - a\r\n  - b\r\ntipo: x\r\n---\r\n\r\n# T\r\n')
    assert fm == {"titulo": "Com aspas", "tags": ["a", "b"], "tipo": "x"}
    assert corpo.strip() == "# T"
    assert vault_busca.separar_frontmatter("sem frontmatter")[0] == {}


def test_limite_padrao_e_maximo(indice):
    assert len(indice.buscar("o OR a horta decisão projeto nota plano")) <= 5
    assert len(indice.buscar("projeto", limite=500)) <= 20
    assert len(indice.buscar("projeto", limite=1)) == 1


@pytest.mark.parametrize("texto", [
    '"', 'a"b', "titulo:horta", "NEAR(a b)", "horta NEAR/2 decisão", "*", "horta*", ")(", "AND OR NOT",
    "x" * (10 * 1024), "\x00", "a\x00b", "- + ^ ~", "{titulo}: horta", "'; DROP TABLE t; --",
])
def test_consulta_hostil_nao_quebra(indice, texto):
    assert isinstance(indice.buscar(texto), list)


def test_consulta_vazia_e_so_stopwords(indice):
    assert indice.buscar("") == []
    assert indice.buscar("   ") == []
    assert indice.buscar('"') == []
    assert isinstance(indice.buscar("de a o"), list)  # só stopwords: mantém as palavras, não quebra
    assert preparar_consulta("de a o") == '"de" OR "a" OR "o"'
    assert preparar_consulta("qual é a decisão sobre horta") == '"decisão" OR "horta"'


def test_preparar_consulta_nunca_deixa_sintaxe():
    assert preparar_consulta('a"b') == '"a""b"'
    assert preparar_consulta("NEAR(a b)") == '"NEAR(a" OR "b)"'
    assert preparar_consulta("titulo:x *") == '"titulo:x"'
    assert len(preparar_consulta("palavra " * 5000).encode()) < 4096 * 6


def test_cache_refaz_so_quando_muda(indice, raiz):
    indice.buscar("horta")
    indice.buscar("plano")
    assert indice.reconstrucoes == 1
    assert indice.buscar("zzzunico") == []

    (raiz / "nova.md").write_text("# Nova\n\n> Nota nova.\n\nzzzunico\n", encoding="utf-8")
    assert _caminhos(indice.buscar("zzzunico")) == ["nova.md"]
    assert indice.reconstrucoes == 2

    nova = raiz / "nova.md"
    nova.write_text("# Nova\n\n> Nota nova.\n\nzzzoutro e mais texto\n", encoding="utf-8")
    assert indice.buscar("zzzunico") == []
    assert _caminhos(indice.buscar("zzzoutro")) == ["nova.md"]
    assert indice.reconstrucoes == 3

    nova.unlink()
    assert indice.buscar("zzzoutro") == []
    assert indice.reconstrucoes == 4
    indice.buscar("horta")
    assert indice.reconstrucoes == 4


def test_arquivo_ilegivel_e_pulado_com_aviso(indice, raiz, caplog):
    (raiz / "binario.md").write_bytes(b"\xff\xfe\x00\x80 zzbinario")
    with caplog.at_level("WARNING", logger="assistente.vault_busca"):
        assert indice.buscar("zzbinario") == []
        assert indice.buscar("horta")
    assert any("binario.md" in r.getMessage() for r in caplog.records)


def test_link_simbolico_para_fora_e_ignorado(indice, raiz, tmp_path):
    fora = tmp_path / "fora.md"
    fora.write_text("# Fora\n\n> Fora do vault.\n\nzzfora\n", encoding="utf-8")
    try:
        (raiz / "link-fora.md").symlink_to(fora)
        (raiz / "link-dentro.md").symlink_to(raiz / "MAPA.md")
    except OSError:
        pytest.skip("sem link simbólico neste sistema")
    assert indice.buscar("zzfora") == []
    assert "link-dentro.md" in _caminhos(indice.buscar("Ponto de entrada", limite=20))


def test_cli_json_e_texto(capsys):
    assert vault_busca.main(["--vault", str(ORIGINAL), "adubo", "--json", "-n", "2"]) == 0
    dados = json.loads(capsys.readouterr().out)
    assert 1 <= len(dados) <= 2
    assert dados[0]["caminho"] == "10-projetos/horta-comunitaria/decisao-compostagem.md"

    assert vault_busca.main(["--vault", str(ORIGINAL), "adubo", "--tipo", "decisao"]) == 0
    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0] == "10-projetos/horta-comunitaria/decisao-compostagem.md — Decisão sobre adubo"
    assert linhas[1].startswith("    Decidimos usar adubo")

    assert vault_busca.main(["--vault", str(ORIGINAL / "nao-existe"), "x"]) == 2


# ---------------- ferramenta no app ----------------

def _app(raiz: Path, tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(raiz))
    return servidor.criar_app(cfg), url


async def test_ferramenta_buscar_vault_pelo_app(raiz, tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "create_proxy", _proxy_falso)
    app, url = _app(raiz, tmp_path)
    segredo = "zzsegredo-da-busca"
    async with Client(app) as c:
        ferramentas = {t.name: t for t in await c.list_tools()}
        assert "buscar_vault" in ferramentas
        assert ferramentas["buscar_vault"].annotations.read_only_hint is True
        assert set(ferramentas["buscar_vault"].input_schema["properties"]) == {"texto", "tipo", "status", "pasta"}
        r = await c.call_tool("buscar_vault", {"texto": "adubo", "tipo": "decisao"})
        assert r.data[0]["caminho"] == "10-projetos/horta-comunitaria/decisao-compostagem.md"
        assert "corpo" not in r.data[0]
        (raiz / "novo.md").write_text(f"# Novo\n\n> r\n\n{segredo}\n", encoding="utf-8")
        assert (await c.call_tool("buscar_vault", {"texto": segredo})).data[0]["caminho"] == "novo.md"
        await c.call_tool("buscar_vault", {"texto": segredo, "pasta": "10-projetos"})

    with Session(create_engine(url)) as s:
        assert s.scalars(select(Auditoria)).all() == []  # leitura: só log e `chamadas`
        chamadas = s.scalars(select(Chamada).where(Chamada.ferramenta == "buscar_vault")).all()
        assert len(chamadas) == 3 and {c.resultado for c in chamadas} == {"ok"}
        assert segredo not in repr([c.__dict__ for c in chamadas])


async def test_vault_nosso_vai_para_a_tabela_vault_e_so_com_caminho(raiz, tmp_path, monkeypatch):
    """Ferramenta nossa do vault (sem prefixo `vault_`) cai na tabela `vault` e só registra o caminho."""
    monkeypatch.setattr(servidor, "create_proxy", _proxy_falso)
    app, url = _app(raiz, tmp_path)
    middleware = next(m for m in app.middleware if isinstance(m, registro.RegistroChamadas))
    assert registro._peca("buscar_vault", middleware._do_vault) == "vault"
    assert registro._peca("buscar_vault") is None
    assert registro._peca("vault_read_note", middleware._do_vault) == "vault"
    assert vault.LEITURAS_VAULT <= middleware._leituras
    assert registro.caminhos_do_vault({"caminho": "a/b.md", "texto": "segredo", "versao": "x"}) == {"caminho": "a/b.md"}
    assert registro.caminhos_do_vault({"texto": "segredo", "pasta": "p"}) == {}


def test_arquivo_de_perguntas_fica_fora_da_busca(tmp_path):
    """O arquivo da medida (2b.10) tem todas as palavras das perguntas; não pode aparecer na busca real."""
    import shutil

    from assistente.vault_busca import IndiceVault
    raiz = tmp_path / "vault"
    shutil.copytree(Path(__file__).parent / "fixtures" / "vault", raiz)
    (raiz / "90-meta" / "perguntas-da-busca.md").write_text("# Perguntas\n\n| adubo compostagem | x |\n", encoding="utf-8")
    achados = [r["caminho"] for r in IndiceVault(raiz).buscar("adubo compostagem", limite=20)]
    assert achados and "90-meta/perguntas-da-busca.md" not in achados
