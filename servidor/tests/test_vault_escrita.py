"""Escrita no vault (Passo 4 da Sprint 2b, 2b.2): escrever_nota com versão e a trava do vault_write_note.

App de verdade (criar_app) sobre uma CÓPIA do vault sintético em tmp_path, com o mcpvault falso em memória
que guarda o que recebeu. Banco em SQLite.
"""

import logging
import os
import shutil
import stat
import threading
from pathlib import Path

import anyio
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import servidor, vault, vault_busca
from assistente.config import Config
from assistente.modelos import Auditoria, Base, Chamada

ORIGINAL = Path(__file__).parent / "fixtures" / "vault"
HORTA = "10-projetos/horta-comunitaria/horta-comunitaria.md"
SEGREDO = "TEXTO-SECRETO-DA-NOTA-ESCRITA"


@pytest.fixture
def raiz(tmp_path) -> Path:
    destino = tmp_path / "vault"
    shutil.copytree(ORIGINAL, destino)
    return destino


@pytest.fixture
def recebidas() -> list:
    return []


@pytest.fixture
def url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    return url


@pytest.fixture
def app(raiz, url, recebidas, monkeypatch):
    falso = FastMCP("mcpvault")

    @falso.tool
    def write_note(path: str, content: str, frontmatter: dict | None = None, mode: str = "overwrite") -> str:
        recebidas.append(("write_note", path, mode))
        return "ok"

    @falso.tool
    def read_note(path: str) -> str:
        return "lida"

    monkeypatch.setattr(servidor, "create_proxy", lambda config: create_proxy(falso))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(raiz))
    return servidor.criar_app(cfg)


def _auditoria(url) -> list[tuple]:
    with Session(create_engine(url)) as s:
        linhas = list(s.scalars(select(Auditoria).order_by(Auditoria.id)))
        pos = {a.id: i for i, a in enumerate(linhas)}
        return [(a.ferramenta, a.tabela, a.acao, a.dados, pos.get(a.registro_id)) for a in linhas]


def _chamadas(url) -> list[Chamada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Chamada).order_by(Chamada.id)))


def _temporarios(raiz: Path) -> list[Path]:
    return [p for p in raiz.rglob("*") if p.name.endswith(".tmp")]


def _arquivos(pasta: Path) -> set[str]:
    return {p.relative_to(pasta).as_posix() for p in pasta.rglob("*")}


async def _ler(c, caminho: str) -> dict:
    return (await c.call_tool("ler_nota", {"caminho": caminho, "relacionadas": False})).data


# ---------------- escrever_nota ----------------

async def test_cria_nota_nova_com_pastas_e_fim_de_linha_intacto(app, raiz):
    conteudo = "---\r\ntitulo: Ideia\r\n---\r\n# Ideia\r\n\r\nAção com acento.\n"
    async with Client(app) as c:
        ferramenta = {t.name: t for t in await c.list_tools()}["escrever_nota"]
        assert ferramenta.annotations.read_only_hint is False
        assert ferramenta.annotations.destructive_hint is True
        assert ferramenta.annotations.idempotent_hint is False
        assert ferramenta.annotations.open_world_hint is False
        assert "modelo" in ferramenta.input_schema["properties"]
        r = (await c.call_tool("escrever_nota", {"caminho": "00-inbox/novas/ideia.md", "conteudo": conteudo,
                                                 "versao": "nova"})).data
        assert r == {"caminho": "00-inbox/novas/ideia.md", "versao": vault.versao_de(conteudo.encode()),
                     "confirmacao": "Criei 00-inbox/novas/ideia.md."}
        assert (await _ler(c, "00-inbox/novas/ideia.md"))["versao"] == r["versao"]
    assert (raiz / "00-inbox/novas/ideia.md").read_bytes() == conteudo.encode("utf-8")
    assert _temporarios(raiz) == []


async def test_nota_nova_tem_o_modo_padrao_do_umask(app, raiz):
    umask = os.umask(0)
    os.umask(umask)
    async with Client(app) as c:
        await c.call_tool("escrever_nota", {"caminho": "00-inbox/m.md", "conteudo": "# M\n", "versao": "nova"})
    assert stat.S_IMODE((raiz / "00-inbox/m.md").stat().st_mode) == 0o666 & ~umask


async def test_nova_recusada_se_ja_existe(app, raiz):
    antes = (raiz / HORTA).read_bytes()
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "x", "versao": "nova"})
    assert str(erro.value) == (f"A nota já existe: {HORTA}. Para acrescentar, use vault_write_note com mode append; "
                               "não troque a nota inteira sem o dono pedir.")
    assert (raiz / HORTA).read_bytes() == antes
    assert _temporarios(raiz) == []


async def test_troca_com_a_versao_certa(app, raiz):
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        novo = lida["conteudo"] + "\nLinha nova.\n"
        r = (await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": novo, "versao": lida["versao"]})).data
        assert r["confirmacao"] == f"Reescrevi {HORTA}." and r["caminho"] == HORTA
        depois = await _ler(c, HORTA)
        assert r["versao"] == depois["versao"] != lida["versao"]
        assert depois["conteudo"] == novo
        # A versão devolvida serve para a próxima troca.
        r2 = (await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# Curta\n", "versao": r["versao"]})).data
        assert r2["versao"] == vault.versao_de(b"# Curta\n")
    assert _temporarios(raiz) == []


async def test_versao_errada_ou_invalida_recusada_e_arquivo_intacto(app, raiz):
    antes = (raiz / HORTA).read_bytes()
    async with Client(app) as c:
        with pytest.raises(ToolError, match="A nota mudou desde a leitura. Leia de novo com ler_nota."):
            await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "x", "versao": "0123456789abcdef"})
        for ruim in ("", "abc", "NOVA", "0123456789ABCDEF", "0123456789abcdef0"):
            with pytest.raises(ToolError, match="versao inválida"):
                await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "x", "versao": ruim})
        with pytest.raises(ToolError, match="Nota não existe: 00-inbox/nao-existe.md"):
            await c.call_tool("escrever_nota", {"caminho": "00-inbox/nao-existe.md", "conteudo": "x",
                                                "versao": "0123456789abcdef"})
    assert (raiz / HORTA).read_bytes() == antes
    assert not (raiz / "00-inbox/nao-existe.md").exists()
    assert _temporarios(raiz) == []


async def test_nota_mudou_entre_ler_e_escrever(app, raiz):
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        (raiz / HORTA).write_text(lida["conteudo"] + "\nDo Syncthing.\n", encoding="utf-8")
        with pytest.raises(ToolError, match="A nota mudou desde a leitura"):
            await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "meu", "versao": lida["versao"]})
    assert (raiz / HORTA).read_text(encoding="utf-8").endswith("Do Syncthing.\n")
    assert _temporarios(raiz) == []


async def test_nota_mudou_depois_do_temporario_segunda_conferencia(app, raiz, monkeypatch):
    """O arquivo muda enquanto o temporário é gravado: a conferência antes do os.replace recusa."""
    original = vault._gravar_temporario

    def _grava_e_syncthing_escreve(pasta, dados, modo=None):
        tmp = original(pasta, dados, modo)
        (raiz / HORTA).write_text("# Do outro aparelho\n", encoding="utf-8")
        return tmp

    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        monkeypatch.setattr(vault, "_gravar_temporario", _grava_e_syncthing_escreve)
        with pytest.raises(ToolError, match="A nota mudou desde a leitura"):
            await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "meu", "versao": lida["versao"]})
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Do outro aparelho\n"
    assert _temporarios(raiz) == []


def test_corrida_em_threads_so_uma_troca_vence(raiz):
    versao = vault.versao_de((raiz / HORTA).read_bytes())
    n = 8
    barreira = threading.Barrier(n)
    resultados: list = [None] * n

    def _escreve(i: int) -> None:
        barreira.wait()
        try:
            resultados[i] = vault.gravar_nota(raiz, HORTA, f"# Versão {i}\n", versao)
        except ToolError as e:
            resultados[i] = e

    threads = [threading.Thread(target=_escreve, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    vencedores = [i for i, r in enumerate(resultados) if isinstance(r, dict)]
    assert len(vencedores) == 1
    assert all(str(r) == vault.NOTA_MUDOU for r in resultados if isinstance(r, ToolError))
    assert (raiz / HORTA).read_text(encoding="utf-8") == f"# Versão {vencedores[0]}\n"
    assert _temporarios(raiz) == []


def test_corrida_em_threads_so_uma_criacao_vence(raiz):
    n = 8
    barreira = threading.Barrier(n)
    resultados: list = [None] * n

    def _cria(i: int) -> None:
        barreira.wait()
        try:
            resultados[i] = vault.gravar_nota(raiz, "00-inbox/corrida.md", f"# {i}\n", "nova")
        except ToolError as e:
            resultados[i] = e

    threads = [threading.Thread(target=_cria, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    vencedores = [i for i, r in enumerate(resultados) if isinstance(r, dict)]
    assert len(vencedores) == 1
    assert all("A nota já existe" in str(r) for r in resultados if isinstance(r, ToolError))
    assert (raiz / "00-inbox/corrida.md").read_text(encoding="utf-8") == f"# {vencedores[0]}\n"
    assert _temporarios(raiz) == []


def test_criacao_sem_link_usa_abrir_exclusivo(raiz, monkeypatch):
    """Sistema sem hard link: cai no open(..., "x"), que também não sobrescreve."""
    def _sem_link(*_a, **_k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(vault.os, "link", _sem_link)
    r = vault.gravar_nota(raiz, "00-inbox/sem-link.md", "# S\n", "nova")
    assert r["confirmacao"] == "Criei 00-inbox/sem-link.md."
    assert (raiz / "00-inbox/sem-link.md").read_bytes() == b"# S\n"
    with pytest.raises(ToolError, match="A nota já existe"):
        vault.gravar_nota(raiz, "00-inbox/sem-link.md", "# outro\n", "nova")
    assert (raiz / "00-inbox/sem-link.md").read_bytes() == b"# S\n"
    assert _temporarios(raiz) == []


async def test_corrida_pelo_app_so_uma_vence(app, raiz):
    async with Client(app) as c:
        versao = (await _ler(c, HORTA))["versao"]
        resultados: list = []

        async def _escreve(texto: str) -> None:
            r = await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": texto, "versao": versao},
                                  raise_on_error=False)
            resultados.append((texto, r.is_error))

        async with anyio.create_task_group() as tg:
            for i in range(4):
                tg.start_soon(_escreve, f"# Corrida {i}\n")
    vencedores = [t for t, erro in resultados if not erro]
    assert len(resultados) == 4 and len(vencedores) == 1
    assert (raiz / HORTA).read_text(encoding="utf-8") == vencedores[0]


@pytest.mark.parametrize("hostil", [
    "../fora.md", "../fora/x.md", "/tmp/x.md", "a/../../fora.md", "~/x.md", "．．/fora.md",
    ".git/x.md", ".obsidian/x.md", "a/.git/x.md", ".stversions/x.md", ".trash/x.md",
    "link-pasta/x.md", "link-arquivo.md", "nota.txt", "", "a\\b.md",
])
async def test_caminho_hostil_recusado_sem_criar_nada(app, raiz, tmp_path, hostil):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "alvo.md").write_text("fora", encoding="utf-8")
    (raiz / "link-pasta").symlink_to(fora)
    (raiz / "link-arquivo.md").symlink_to(fora / "alvo.md")
    (raiz / ".git").mkdir()
    antes_vault, antes_tmp = _arquivos(raiz), _arquivos(tmp_path)
    versao_fora = vault.versao_de(b"fora")
    async with Client(app) as c:
        for versao in ("nova", versao_fora):
            with pytest.raises(ToolError):
                await c.call_tool("escrever_nota", {"caminho": hostil, "conteudo": "invasor", "versao": versao})
    assert (fora / "alvo.md").read_text(encoding="utf-8") == "fora"
    assert _arquivos(fora) == {"alvo.md"}
    assert _arquivos(raiz) == antes_vault
    assert _arquivos(tmp_path) - {"teste.db"} == antes_tmp - {"teste.db"}


async def test_link_simbolico_dentro_do_vault_troca_o_alvo(app, raiz):
    """Link para uma nota do próprio vault: escreve no alvo e o link continua link."""
    (raiz / "atalho.md").symlink_to(raiz / HORTA)
    async with Client(app) as c:
        lida = await _ler(c, "atalho.md")
        await c.call_tool("escrever_nota", {"caminho": "atalho.md", "conteudo": "# Pelo atalho\n",
                                            "versao": lida["versao"]})
    assert (raiz / "atalho.md").is_symlink()
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Pelo atalho\n"


async def test_permissoes_preservadas(app, raiz):
    os.chmod(raiz / HORTA, 0o640)
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# Nova\n", "versao": lida["versao"]})
    assert stat.S_IMODE((raiz / HORTA).stat().st_mode) == 0o640


async def test_conteudo_grande_nul_ou_invalido_recusado(app, raiz):
    async with Client(app) as c:
        for conteudo, erro in [("a" * 200_001, "até 200000 caracteres"), ("a\x00b", "NUL"), ("\ud800", "UTF-8")]:
            with pytest.raises(ToolError, match=erro):
                await c.call_tool("escrever_nota", {"caminho": "00-inbox/g.md", "conteudo": conteudo, "versao": "nova"})
        assert not (raiz / "00-inbox/g.md").exists()
        r = await c.call_tool("escrever_nota", {"caminho": "00-inbox/g.md", "conteudo": "a" * 200_000, "versao": "nova"})
        assert r.data["confirmacao"] == "Criei 00-inbox/g.md."
    assert _temporarios(raiz) == []


async def test_conteudo_vazio_recusado_ao_criar_e_ao_trocar(app, raiz):
    antes = (raiz / HORTA).read_bytes()
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        for vazio in ("", "   ", "\n\n", " \t\r\n"):
            for caminho, versao in ((HORTA, lida["versao"]), ("00-inbox/vazia.md", "nova")):
                with pytest.raises(ToolError) as erro:
                    await c.call_tool("escrever_nota", {"caminho": caminho, "conteudo": vazio, "versao": versao})
                assert str(erro.value) == "Conteúdo vazio: nada foi gravado. Nada se apaga no vault."
    assert (raiz / HORTA).read_bytes() == antes
    assert not (raiz / "00-inbox/vazia.md").exists()
    assert _temporarios(raiz) == []


async def test_nota_maior_que_o_limite_nao_e_trocada(app, raiz):
    """ler_nota corta a nota grande e não dá versão; a troca com a versão do arquivo inteiro é recusada."""
    grande = "x" * 200_000 + "\nFIM IMPORTANTE\n"
    (raiz / "grande.md").write_text(grande, encoding="utf-8")
    async with Client(app) as c:
        lida = await _ler(c, "grande.md")
        assert lida["versao"] is None and lida["cortado"] is True
        assert lida["aviso"] == ("Nota maior que o limite: lida só em parte. Não dá para trocar a nota inteira; "
                                 "use vault_patch_note ou vault_write_note com mode append.")
        versao_real = vault.versao_de(grande.encode())
        with pytest.raises(ToolError) as erro:
            await c.call_tool("escrever_nota", {"caminho": "grande.md", "conteudo": lida["conteudo"][:-5] + "nova\n",
                                                "versao": versao_real})
    assert str(erro.value) == ("Nota maior que o limite. Não dá para trocar a nota inteira; "
                               "use vault_patch_note ou vault_write_note com mode append.")
    assert (raiz / "grande.md").read_text(encoding="utf-8") == grande
    assert _temporarios(raiz) == []


async def test_nota_fora_de_utf8_so_leitura(app, raiz):
    """Bytes que não são UTF-8: ler_nota mostra o texto com substituição, sem versão; a troca é recusada."""
    bruto = "café ".encode() + b"caf\xe9 latin1\n"
    (raiz / "latin.md").write_bytes(bruto)
    async with Client(app) as c:
        lida = await _ler(c, "latin.md")
        assert lida["conteudo"] == "café caf\ufffd latin1\n"
        assert lida["versao"] is None
        assert lida["aviso"] == "A nota não está em UTF-8: só leitura. Edite no Obsidian."
        assert "cortado" not in lida
        with pytest.raises(ToolError) as erro:
            await c.call_tool("escrever_nota", {"caminho": "latin.md", "conteudo": lida["conteudo"] + "mais\n",
                                                "versao": vault.versao_de(bruto)})
    assert str(erro.value) == "A nota não está em UTF-8: só leitura. Edite no Obsidian."
    assert (raiz / "latin.md").read_bytes() == bruto
    assert _temporarios(raiz) == []


async def test_nota_normal_vem_com_versao_e_sem_aviso(app, raiz):
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
    assert lida["versao"] == vault.versao_de((raiz / HORTA).read_bytes())
    assert "aviso" not in lida and "cortado" not in lida


def test_temporario_fica_fora_da_busca(raiz):
    (raiz / "00-inbox" / ".escrever-nota-0123456789abcdef.tmp").write_text("# T\n", encoding="utf-8")
    nomes = {p.name for p, _, _ in vault_busca.listar_arquivos(raiz)}
    assert nomes and not any(n.endswith(".tmp") for n in nomes)


# ---------------- trava do vault_write_note ----------------

@pytest.mark.parametrize("args", [
    {}, {"mode": "overwrite"}, {"mode": "APPEND"}, {"mode": None}, {"mode": ["append"]}, {"mode": ""},
])
async def test_write_note_sem_append_recusada_sem_chegar_a_peca(app, url, recebidas, args):
    async with Client(app) as c:
        with pytest.raises(ToolError, match="vault_write_note só acrescenta"):
            await c.call_tool("vault_write_note", {"path": "a.md", "content": SEGREDO, **args})
    assert recebidas == []
    assert _auditoria(url) == [("vault_write_note", "vault", "escrever", {"caminho": "a.md"}, None),
                               ("vault_write_note", "vault", "erro", {"caminho": "a.md"}, 0)]
    assert [c.resultado for c in _chamadas(url)] == ["erro"]


async def test_write_note_append_e_prepend_passam(app, url, recebidas):
    async with Client(app) as c:
        for modo in ("append", "prepend"):
            assert (await c.call_tool("vault_write_note", {"path": "a.md", "content": "x", "mode": modo})).data == "ok"
    assert recebidas == [("write_note", "a.md", "append"), ("write_note", "a.md", "prepend")]
    assert [a[2] for a in _auditoria(url)] == ["escrever", "ok", "escrever", "ok"]


def test_mensagem_da_trava():
    assert vault.RECUSA_WRITE_NOTE == ("vault_write_note só acrescenta (mode append ou prepend). "
                                       "Para trocar a nota inteira, use ler_nota e escrever_nota.")


# ---------------- registro ----------------

async def test_auditoria_so_com_o_caminho_e_conteudo_fora_do_banco_e_do_log(app, raiz, url, caplog):
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            r = (await c.call_tool("escrever_nota", {"caminho": "00-inbox/s.md", "conteudo": f"# S\n{SEGREDO}\n",
                                                     "versao": "nova", "modelo": "claude-opus-5-5"})).data
            with pytest.raises(ToolError, match="mudou"):
                await c.call_tool("escrever_nota", {"caminho": "00-inbox/s.md", "conteudo": SEGREDO,
                                                    "versao": "0123456789abcdef"})
            await c.call_tool("escrever_nota", {"caminho": "00-inbox/s.md", "conteudo": f"{SEGREDO}!",
                                                "versao": r["versao"]})
    assert _auditoria(url) == [
        ("escrever_nota", "vault", "escrever", {"caminho": "00-inbox/s.md"}, None),
        ("escrever_nota", "vault", "ok", {"caminho": "00-inbox/s.md"}, 0),
        ("escrever_nota", "vault", "escrever", {"caminho": "00-inbox/s.md"}, None),
        ("escrever_nota", "vault", "erro", {"caminho": "00-inbox/s.md"}, 2),
        ("escrever_nota", "vault", "escrever", {"caminho": "00-inbox/s.md"}, None),
        ("escrever_nota", "vault", "ok", {"caminho": "00-inbox/s.md"}, 4),
    ]
    chamadas = _chamadas(url)
    assert [(c.ferramenta, c.resultado, c.modelo_declarado) for c in chamadas] == [
        ("escrever_nota", "ok", "claude-opus-5-5"), ("escrever_nota", "erro", None), ("escrever_nota", "ok", None)]
    with Session(create_engine(url)) as s:
        tudo = repr([a.__dict__ for a in s.scalars(select(Auditoria))] + [c.__dict__ for c in s.scalars(select(Chamada))])
    assert SEGREDO not in tudo
    assert SEGREDO not in caplog.text
    assert (raiz / "00-inbox/s.md").read_text(encoding="utf-8") == f"{SEGREDO}!"
