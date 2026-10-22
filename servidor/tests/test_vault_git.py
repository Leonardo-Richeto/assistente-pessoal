"""Git do vault (Passo 6 da Sprint 2b, 2b.4): commit por escrita, historico_nota e restaurar_nota.

App de verdade (criar_app) sobre uma CÓPIA do vault sintético em tmp_path, com `git init` e um commit inicial.
O mcpvault falso grava no disco do tmp, para o teste ver o commit. Precisa do `git` do sistema.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import servidor, vault, vault_git
from assistente.config import Config
from assistente.modelos import Auditoria, Base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="precisa do git do sistema")

ORIGINAL = Path(__file__).parent / "fixtures" / "vault"
HORTA = "10-projetos/horta-comunitaria/horta-comunitaria.md"
SEGREDO = "TEXTO-SECRETO-DA-NOTA-COMITADA"
AUTOR = "claude-app <claude-app@localhost>"


def _git(pasta: Path, *args: str, env: dict | None = None) -> str:
    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    ambiente.update(env or {})
    r = subprocess.run(["git", "-C", str(pasta), "-c", "user.name=Teste", "-c", "user.email=teste@localhost",
                        "-c", "commit.gpgsign=false", *args], capture_output=True, env=ambiente, check=True)
    return r.stdout.decode()


def _git_falso(pasta: Path, monkeypatch, corpo: str) -> Path:
    """Põe na frente do PATH um `git` falso (bash) com este corpo; devolve o lock falso ($LOCK_FALSO) dele."""
    bin_falso = pasta / "bin-falso"
    bin_falso.mkdir(exist_ok=True)
    script = bin_falso / "git"
    script.write_text(f"#!/bin/bash\n{corpo}\n", encoding="utf-8")
    script.chmod(0o755)
    lock = pasta / "lock-falso"
    monkeypatch.setenv("PATH", f"{bin_falso}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LOCK_FALSO", str(lock))
    return lock


def _iniciar(pasta: Path) -> None:
    _git(pasta, "-c", "init.defaultBranch=main", "init", "-q")
    _git(pasta, "add", "-A")
    _git(pasta, "commit", "-q", "-m", "inicial")


def _commits(pasta: Path) -> int:
    return int(_git(pasta, "rev-list", "--count", "HEAD").strip())


def _ultimo(pasta: Path) -> tuple[str, str, list[str]]:
    """(autor, mensagem, arquivos) do HEAD."""
    autor = _git(pasta, "log", "-1", "--format=%an <%ae>").strip()
    mensagem = _git(pasta, "log", "-1", "--format=%B").strip()
    arquivos = _git(pasta, "-c", "core.quotePath=false", "show", "--name-only", "--format=", "HEAD").split()
    return autor, mensagem, arquivos


@pytest.fixture
def raiz(tmp_path) -> Path:
    destino = tmp_path / "vault"
    shutil.copytree(ORIGINAL, destino)
    _iniciar(destino)
    return destino


@pytest.fixture
def url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    Base.metadata.create_all(create_engine(url))
    return url


def _no_vault(raiz: Path, path: str) -> Path:
    """Como o normalizePath do mcpvault 0.16.0: tira a raiz absoluta do começo, ou uma `/` inicial."""
    p = path.strip()
    prefixo = os.path.realpath(raiz)
    if p.startswith(prefixo + "/"):
        p = p[len(prefixo) + 1:]
    elif p.startswith("/"):
        p = p[1:]
    return raiz / p


CHAMADAS_PECA: list[str] = []  # caminhos que a peça falsa recebeu (para ver que a recusa não chega à peça)


def _criar_app(raiz: Path, url: str, monkeypatch):
    falso = FastMCP("mcpvault")
    CHAMADAS_PECA.clear()

    @falso.tool
    def write_note(path: str, content: str, frontmatter: dict | None = None, mode: str = "overwrite") -> str:
        CHAMADAS_PECA.append(path)
        alvo = _no_vault(raiz, path)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        antes = alvo.read_text(encoding="utf-8") if alvo.exists() else ""
        alvo.write_text({"append": antes + content, "prepend": content + antes}.get(mode, content), encoding="utf-8")
        return "ok"

    @falso.tool
    def patch_note(path: str, oldString: str, newString: str) -> str:
        (raiz / path).write_text("mudou e depois falhou\n", encoding="utf-8")  # escreveu, mas devolve erro
        raise ToolError("oldString não encontrado")

    @falso.tool
    def update_frontmatter(path: str, frontmatter: dict) -> str:
        alvo = raiz / path
        alvo.write_text(alvo.read_text(encoding="utf-8") + "\n<!-- fm -->\n", encoding="utf-8")
        return "ok"

    @falso.tool
    def manage_tags(path: str, operation: str, tags: list[str] | None = None) -> str:
        if operation == "add":
            alvo = raiz / path
            alvo.write_text(alvo.read_text(encoding="utf-8") + "\n#nova\n", encoding="utf-8")
        return "ok"  # list e remove: não mexem no arquivo

    monkeypatch.setattr(servidor, "create_proxy", lambda config: create_proxy(falso))
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(raiz))
    return servidor.criar_app(cfg)


@pytest.fixture
def app(raiz, url, monkeypatch):
    return _criar_app(raiz, url, monkeypatch)


def _avisos(caplog) -> list[str]:
    """WARNING ou acima do vault e do git (o fastmcp loga ERROR em toda ToolError, e a recusa é esperada)."""
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and r.name.startswith("assistente.vault")]


async def _ler(c, caminho: str) -> dict:
    return (await c.call_tool("ler_nota", {"caminho": caminho, "relacionadas": False})).data


# ---------------- commit por escrita ----------------

async def test_escrever_nota_comita_so_o_arquivo_escrito(app, raiz, caplog):
    outra_modificada = "20-areas/perfil-do-leonardo.md"
    outra_staged = "00-inbox/ideia-bicicleta.md"
    assert (raiz / outra_modificada).is_file() and (raiz / outra_staged).is_file()
    (raiz / outra_modificada).write_text("mudada no disco, fora do index\n", encoding="utf-8")
    (raiz / outra_staged).write_text("mudada e staged\n", encoding="utf-8")
    _git(raiz, "add", "--", outra_staged)
    antes = _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("escrever_nota", {"caminho": "00-inbox/nova.md", "conteudo": f"# Nova\n{SEGREDO}\n",
                                                "versao": "nova"})
    assert _commits(raiz) == antes + 1  # um commit só: o middleware não comita escrever_nota de novo
    assert _ultimo(raiz) == (AUTOR, "claude-app: escrever_nota 00-inbox/nova.md", ["00-inbox/nova.md"])
    assert _git(raiz, "diff", "--cached", "--name-only").split() == [outra_staged]
    assert _git(raiz, "diff", "--name-only").split() == [outra_modificada]
    assert SEGREDO not in _git(raiz, "log", "--format=%an%ae%s%b") and SEGREDO not in caplog.text
    assert _avisos(caplog) == []


async def test_troca_comita_com_a_mensagem_da_ferramenta(app, raiz):
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# Outra\n", "versao": lida["versao"]})
    assert _ultimo(raiz) == (AUTOR, f"claude-app: escrever_nota {HORTA}", [HORTA])
    assert _git(raiz, "status", "--porcelain") == ""


@pytest.mark.parametrize("ferramenta,args", [
    ("vault_write_note", {"path": "00-inbox/ideia-bicicleta.md", "content": "\nmais\n", "mode": "append"}),
    ("vault_write_note", {"path": "00-inbox/nova-pelo-mcpvault.md", "content": "# N\n", "mode": "append"}),
    ("vault_update_frontmatter", {"path": "00-inbox/ideia-bicicleta.md", "frontmatter": {"status": "ativo"}}),
    ("vault_manage_tags", {"path": "00-inbox/ideia-bicicleta.md", "operation": "add", "tags": ["x"]}),
])
async def test_escrita_do_mcpvault_comita(app, raiz, ferramenta, args):
    antes = _commits(raiz)
    async with Client(app) as c:
        await c.call_tool(ferramenta, args)
    assert _commits(raiz) == antes + 1
    assert _ultimo(raiz) == (AUTOR, f"claude-app: {ferramenta} {args['path']}", [args["path"]])


async def test_manage_tags_list_e_nada_mudou_nao_comitam_nem_avisam(app, raiz, caplog):
    antes = _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("vault_manage_tags", {"path": "00-inbox/ideia-bicicleta.md", "operation": "list"})
            # remove na peça falsa não mexe no arquivo: "nada a comitar" não é erro.
            await c.call_tool("vault_manage_tags", {"path": "00-inbox/ideia-bicicleta.md", "operation": "remove",
                                                    "tags": ["x"]})
    assert _commits(raiz) == antes
    assert "Nada a comitar em 00-inbox/ideia-bicicleta.md" in caplog.text
    assert caplog.text.count("Nada a comitar") == 1  # list nem tenta
    assert _avisos(caplog) == []


async def test_escrita_com_erro_nao_comita(app, raiz):
    antes = _commits(raiz)
    async with Client(app) as c:
        with pytest.raises(ToolError):  # a peça escreveu no disco e devolveu erro
            await c.call_tool("vault_patch_note", {"path": "00-inbox/ideia-bicicleta.md", "oldString": "a",
                                                   "newString": "b"})
        with pytest.raises(ToolError, match="vault_write_note só acrescenta"):  # trava: nem chega à peça
            await c.call_tool("vault_write_note", {"path": "00-inbox/ideia-bicicleta.md", "content": "x"})
        with pytest.raises(ToolError, match="A nota mudou"):
            await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "x", "versao": "0123456789abcdef"})
    assert _commits(raiz) == antes
    assert _git(raiz, "diff", "--name-only").split() == ["00-inbox/ideia-bicicleta.md"]


async def test_caminho_invalido_do_mcpvault_nao_comita(app, raiz):
    antes = _commits(raiz)
    async with Client(app) as c:
        for caminho in ("00-inbox/sem-extensao", ".obsidian/x.md", "00-inbox/../00-inbox/x.md"):
            await c.call_tool("vault_write_note", {"path": caminho, "content": "x", "mode": "append"})
    assert _commits(raiz) == antes


def test_index_lock_temporario_comita_na_segunda_ou_terceira_tentativa(raiz, monkeypatch):
    (raiz / "00-inbox/l.md").write_text("# L\n", encoding="utf-8")
    trava = raiz / ".git" / "index.lock"
    trava.write_bytes(b"")
    tentativas = []
    original = vault_git._tentar_commit

    def _conta(*a):
        r = original(*a)
        tentativas.append(r[0])
        return r

    monkeypatch.setattr(vault_git, "_tentar_commit", _conta)
    threading.Timer(0.3, trava.unlink).start()
    assert vault_git.commitar(raiz, "00-inbox/l.md", "claude-app: teste 00-inbox/l.md") is True
    assert tentativas[0] == "lock" and tentativas[-1] == "ok" and 2 <= len(tentativas) <= 3
    assert _ultimo(raiz) == (AUTOR, "claude-app: teste 00-inbox/l.md", ["00-inbox/l.md"])


async def test_index_lock_permanente_avisa_e_a_escrita_vale(app, raiz, monkeypatch, caplog):
    monkeypatch.setattr(vault_git, "ESPERAS_LOCK", (0.01, 0.01, 0.01))
    (raiz / ".git" / "index.lock").write_bytes(b"")
    antes = _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            r = (await c.call_tool("escrever_nota", {"caminho": "00-inbox/presa.md", "conteudo": f"# P\n{SEGREDO}\n",
                                                     "versao": "nova"})).data
    assert r["confirmacao"] == "Criei 00-inbox/presa.md."
    assert (raiz / "00-inbox/presa.md").read_text(encoding="utf-8") == f"# P\n{SEGREDO}\n"
    assert _avisos(caplog) == ["Commit do vault falhou em 00-inbox/presa.md (index.lock ocupado); a escrita vale"]
    assert SEGREDO not in caplog.text
    (raiz / ".git" / "index.lock").unlink()
    assert _commits(raiz) == antes


async def test_vault_sem_git_escreve_sem_commit_e_sem_erro(tmp_path, url, monkeypatch, caplog):
    raiz = tmp_path / "vault"
    shutil.copytree(ORIGINAL, raiz)
    app = _criar_app(raiz, url, monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("escrever_nota", {"caminho": "00-inbox/s.md", "conteudo": "# S\n", "versao": "nova"})
            await c.call_tool("vault_write_note", {"path": "00-inbox/s.md", "content": "x", "mode": "append"})
            for ferramenta, args in (("historico_nota", {"caminho": HORTA}),
                                     ("restaurar_nota", {"caminho": HORTA, "versao_git": "0123456"})):
                with pytest.raises(ToolError) as erro:
                    await c.call_tool(ferramenta, args)
                assert str(erro.value) == "O vault não tem histórico (sem git)."
    assert (raiz / "00-inbox/s.md").read_text(encoding="utf-8") == "# S\nx"
    assert not (raiz / ".git").exists()
    assert "Vault sem .git na raiz" in caplog.text
    assert _avisos(caplog) == []


async def test_git_numa_pasta_acima_nao_conta(tmp_path, url, monkeypatch):
    de_fora = tmp_path / "repo-de-fora"
    raiz = de_fora / "vault"
    shutil.copytree(ORIGINAL, raiz)
    _iniciar(de_fora)
    app = _criar_app(raiz, url, monkeypatch)
    async with Client(app) as c:
        await c.call_tool("escrever_nota", {"caminho": "00-inbox/s.md", "conteudo": "# S\n", "versao": "nova"})
        with pytest.raises(ToolError, match=r"O vault não tem histórico \(sem git\)\."):
            await c.call_tool("historico_nota", {"caminho": HORTA})
    assert _commits(de_fora) == 1
    assert _git(de_fora, "status", "--porcelain").strip() == "?? vault/00-inbox/s.md"


def test_variaveis_git_herdadas_nao_desviam_o_commit(raiz, tmp_path, monkeypatch):
    outro = tmp_path / "outro"
    outro.mkdir()
    _git(outro, "-c", "init.defaultBranch=main", "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(outro / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outro))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outro / ".git" / "index"))
    (raiz / "00-inbox/e.md").write_text("# E\n", encoding="utf-8")
    assert vault_git.commitar(raiz, "00-inbox/e.md", "claude-app: teste 00-inbox/e.md") is True
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert _ultimo(raiz)[2] == ["00-inbox/e.md"]


def test_git_ausente_ou_lento_so_avisa(raiz, monkeypatch, caplog):
    (raiz / "00-inbox/g.md").write_text("# G\n", encoding="utf-8")

    def _sem_git(*_a, **_k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(vault_git.subprocess, "Popen", _sem_git)
    with caplog.at_level(logging.WARNING, logger="assistente"):
        assert vault_git.commitar(raiz, "00-inbox/g.md", "m") is False
    monkeypatch.undo()
    _git_falso(raiz.parent, monkeypatch, "sleep 30 & wait")
    monkeypatch.setattr(vault_git, "TIMEOUT_LEITURA", 0.3)
    with caplog.at_level(logging.WARNING, logger="assistente"):
        assert vault_git.commitar(raiz, "00-inbox/g.md", "m") is False
    assert [r.getMessage() for r in caplog.records] == [
        "Commit do vault falhou em 00-inbox/g.md (git não instalado); a escrita vale",
        "Commit do vault falhou em 00-inbox/g.md (git rev-parse passou de 0.3 s); a escrita vale"]


# ---------------- nenhum argumento vira opção nem padrão do git ----------------

async def test_nome_com_hifen_ou_curinga_comita_so_aquele_arquivo(app, raiz):
    (raiz / "00-inbox/ab.md").write_text("# AB\n", encoding="utf-8")
    (raiz / "00-inbox/a[b].md").write_text("# colchete\n", encoding="utf-8")
    async with Client(app) as c:
        for caminho in ("-n.md", "00-inbox/--all.md", "00-inbox/a*.md", "00-inbox/a?.md"):
            await c.call_tool("escrever_nota", {"caminho": caminho, "conteudo": "# x\n", "versao": "nova"})
            assert _ultimo(raiz)[2] == [caminho]
        # Pathspec literal: "a[b].md" não casa com "ab.md".
        await c.call_tool("vault_write_note", {"path": "00-inbox/a[b].md", "content": "+\n", "mode": "append"})
    assert _ultimo(raiz)[2] == ["00-inbox/a[b].md"]
    assert set(_git(raiz, "status", "--porcelain").split()) == {"??", "00-inbox/ab.md"}


@pytest.mark.parametrize("ruim", ["", "HEAD", "-n", "--output=/tmp/x", "ABCDEF1", "abc12", "0123456 ", "main",
                                  "0" * 41, "0123456:x", "0123456^{tree}", "@{-1}"])
async def test_versao_git_so_hexadecimal(app, raiz, ruim):
    async with Client(app) as c:
        with pytest.raises(ToolError, match="versao_git inválida"):
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": ruim})


# ---------------- historico_nota ----------------

async def test_historico_ordem_fuso_e_limite(app, raiz):
    # Commit à mão com data fixa: 2026-01-15 03:30 UTC = 00:30 em São Paulo.
    (raiz / HORTA).write_text("# Manual\n", encoding="utf-8")
    data = "2026-01-15T03:30:00+00:00"
    _git(raiz, "commit", "-q", "-m", "manual", "--", HORTA, env={"GIT_AUTHOR_DATE": data, "GIT_COMMITTER_DATE": data})
    async with Client(app) as c:
        ferramenta = {t.name: t for t in await c.list_tools()}["historico_nota"]
        assert ferramenta.annotations.read_only_hint is True
        versao = (await _ler(c, HORTA))["versao"]
        for i in range(3):
            versao = (await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": f"# V{i}\n",
                                                          "versao": versao})).data["versao"]
        h = (await c.call_tool("historico_nota", {"caminho": HORTA})).data
        assert [v["mensagem"] for v in h] == [f"claude-app: escrever_nota {HORTA}"] * 3 + ["manual", "inicial"]
        assert [v["autor"] for v in h] == ["claude-app"] * 3 + ["Teste", "Teste"]
        assert h[3]["data"] == "2026-01-15 00:30"
        assert all(len(v["versao_git"]) == 12 and set(v["versao_git"]) <= set("0123456789abcdef") for v in h)
        assert [v["versao_git"] for v in h] == _git(raiz, "log", "--format=%h", "--abbrev=12", "--", HORTA).split()
        agora = datetime.now(vault.FUSO).strftime("%Y-%m-%d %H:")
        assert h[0]["data"].startswith(agora[:10])
        assert len((await c.call_tool("historico_nota", {"caminho": HORTA, "n": 2})).data) == 2
        assert len((await c.call_tool("historico_nota", {"caminho": HORTA, "n": 0})).data) == 1
        assert len((await c.call_tool("historico_nota", {"caminho": HORTA, "n": 999})).data) == 5
        assert (await c.call_tool("historico_nota", {"caminho": "00-inbox/nunca-existiu.md"})).data == []
        with pytest.raises(ToolError, match="Caminho de nota inválido"):
            await c.call_tool("historico_nota", {"caminho": "../fora.md"})


async def test_historico_segue_troca_de_nome(app, raiz):
    _git(raiz, "mv", HORTA, "10-projetos/horta.md")
    _git(raiz, "commit", "-q", "-m", "renomeia")
    async with Client(app) as c:
        h = (await c.call_tool("historico_nota", {"caminho": "10-projetos/horta.md"})).data
    assert [v["mensagem"] for v in h] == ["renomeia", "inicial"]


def test_historico_de_repositorio_sem_commit(tmp_path):
    raiz = tmp_path / "v"
    raiz.mkdir()
    _git(raiz, "init", "-q")
    assert vault_git.historico(raiz, "a.md") == []


# ---------------- restaurar_nota ----------------

async def test_restaurar_volta_o_conteudo_com_commit_novo(app, raiz, url):
    original = (raiz / HORTA).read_bytes()
    async with Client(app) as c:
        ferramenta = {t.name: t for t in await c.list_tools()}["restaurar_nota"]
        assert ferramenta.annotations.read_only_hint is False and ferramenta.annotations.destructive_hint is True
        assert "modelo" in ferramenta.input_schema["properties"]
        lida = await _ler(c, HORTA)
        await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# Estragada\n", "versao": lida["versao"]})
        h = (await c.call_tool("historico_nota", {"caminho": HORTA})).data
        inicial = h[-1]
        antes = _commits(raiz)
        r = (await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial["versao_git"],
                                                  "modelo": "claude-opus-5-5"})).data
        assert r == {"caminho": HORTA, "versao": vault.versao_de(original),
                     "versao_git_restaurada": inicial["versao_git"],
                     "confirmacao": f"Restaurei {HORTA} para a versão de {inicial['data']}."}
        assert (raiz / HORTA).read_bytes() == original
        assert _commits(raiz) == antes + 1
        assert _ultimo(raiz) == (AUTOR, f"claude-app: restaurar_nota {HORTA} ({inicial['versao_git']})", [HORTA])
        depois = (await c.call_tool("historico_nota", {"caminho": HORTA})).data
        assert [v["versao_git"] for v in depois[1:]] == [v["versao_git"] for v in h]  # a versão estragada ficou
        # De novo: nada muda e não há commit.
        r2 = (await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial["versao_git"][:7]})).data
        assert r2["confirmacao"] == "Nada mudou: a nota já está nessa versão."
        assert r2["versao"] == vault.versao_de(original)
        assert _commits(raiz) == antes + 1
        # Dá para restaurar de volta a versão estragada.
        await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": h[0]["versao_git"]})
        assert (raiz / HORTA).read_text(encoding="utf-8") == "# Estragada\n"
    # Auditoria: só o caminho, sem a versão.
    with Session(create_engine(url)) as s:
        linhas = [(a.ferramenta, a.tabela, a.acao, a.dados) for a in s.scalars(select(Auditoria).order_by(Auditoria.id))
                  if a.ferramenta == "restaurar_nota"]
    assert linhas[:2] == [("restaurar_nota", "vault", "escrever", {"caminho": HORTA}),
                          ("restaurar_nota", "vault", "ok", {"caminho": HORTA})]


async def test_restaurar_nota_apagada_cria_de_novo(app, raiz):
    original = (raiz / HORTA).read_bytes()
    (raiz / HORTA).unlink()
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    async with Client(app) as c:
        r = (await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial})).data
    assert r["versao_git_restaurada"] == inicial[:12]
    assert (raiz / HORTA).read_bytes() == original
    assert _git(raiz, "status", "--porcelain") == ""


async def test_restaurar_versao_que_nao_existe_ou_nao_tem_a_nota(app, raiz):
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    async with Client(app) as c:
        await c.call_tool("escrever_nota", {"caminho": "00-inbox/depois.md", "conteudo": "# D\n", "versao": "nova"})
        with pytest.raises(ToolError, match="Essa versão não existe no histórico do vault."):
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": "0123456789abcdef"})
        with pytest.raises(ToolError, match="Essa versão não tem a nota com este caminho."):
            await c.call_tool("restaurar_nota", {"caminho": "00-inbox/depois.md", "versao_git": inicial})
        # Nome antigo (antes de um git mv) não vale: só o caminho atual.
        _git(raiz, "mv", HORTA, "10-projetos/horta.md")
        _git(raiz, "commit", "-q", "-m", "renomeia")
        with pytest.raises(ToolError, match="Essa versão não tem a nota com este caminho."):
            await c.call_tool("restaurar_nota", {"caminho": "10-projetos/horta.md", "versao_git": inicial})
        # Pasta (com nome terminado em .md) não é nota.
        (raiz / "00-inbox/pasta.md").mkdir()
        (raiz / "00-inbox/pasta.md/x.md").write_text("# X\n", encoding="utf-8")
        _git(raiz, "add", "--", "00-inbox/pasta.md/x.md")
        _git(raiz, "commit", "-q", "-m", "pasta")
        com_pasta = _git(raiz, "rev-parse", "HEAD").strip()
        shutil.rmtree(raiz / "00-inbox/pasta.md")
        with pytest.raises(ToolError, match="Essa versão não tem a nota com este caminho."):
            await c.call_tool("restaurar_nota", {"caminho": "00-inbox/pasta.md", "versao_git": com_pasta})
    assert (raiz / "00-inbox/depois.md").read_text(encoding="utf-8") == "# D\n"


async def test_restaurar_recusa_versao_fora_de_utf8(app, raiz):
    (raiz / HORTA).write_bytes(b"caf\xe9 latin1\n")
    _git(raiz, "commit", "-q", "-m", "latin1", "--", HORTA)
    latin = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).write_text("# Atual\n", encoding="utf-8")
    _git(raiz, "commit", "-q", "-m", "utf8", "--", HORTA)
    antes = _commits(raiz)
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Essa versão da nota não está em UTF-8"):
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": latin})
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Atual\n"
    assert _commits(raiz) == antes


async def test_restaurar_versao_vazia_e_recusada(app, raiz):
    (raiz / "00-inbox/vazia.md").write_bytes(b"")
    _git(raiz, "add", "--", "00-inbox/vazia.md")
    _git(raiz, "commit", "-q", "-m", "vazia")
    vazia = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / "00-inbox/vazia.md").write_text("# Cheia\n", encoding="utf-8")
    async with Client(app) as c:
        with pytest.raises(ToolError, match="Conteúdo vazio: nada foi gravado"):
            await c.call_tool("restaurar_nota", {"caminho": "00-inbox/vazia.md", "versao_git": vazia})
    assert (raiz / "00-inbox/vazia.md").read_text(encoding="utf-8") == "# Cheia\n"


# ---------------- correções do revisor do Passo 6 ----------------

RECUSA_FOTO = "Não consegui guardar a versão atual no histórico; nada foi trocado."
AUTOR_FOTO = "vault <vault@localhost>"


def _log_p(pasta: Path, caminho: str) -> str:
    return _git(pasta, "log", "-p", "--format=%x1e%an <%ae>|%s", "--", caminho)


async def test_restaurar_guarda_antes_a_edicao_do_dono_sem_commit(app, raiz):
    v1 = (raiz / HORTA).read_text(encoding="utf-8")
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).write_text("# V2 do dono, sem commit\n", encoding="utf-8")
    async with Client(app) as c:
        await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial})
    assert (raiz / HORTA).read_text(encoding="utf-8") == v1
    commits = [b.splitlines()[0] for b in _log_p(raiz, HORTA).split("\x1e")[1:]]
    assert commits == [f"{AUTOR}|claude-app: restaurar_nota {HORTA} ({inicial[:12]})",
                       f"{AUTOR_FOTO}|vault: estado antes de restaurar_nota {HORTA}",
                       "Teste <teste@localhost>|inicial"]
    assert _git(raiz, "show", f"HEAD~1:{HORTA}") == "# V2 do dono, sem commit\n"
    assert "+# V2 do dono, sem commit" in _log_p(raiz, HORTA)
    assert _git(raiz, "status", "--porcelain") == ""


async def test_escrever_nota_guarda_antes_a_edicao_do_dono_sem_commit(app, raiz):
    (raiz / HORTA).write_text("# V2 do dono\n", encoding="utf-8")
    antes = _commits(raiz)
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# V3\n", "versao": lida["versao"]})
    assert _commits(raiz) == antes + 2
    assert _git(raiz, "show", f"HEAD~1:{HORTA}") == "# V2 do dono\n"
    assert _git(raiz, "log", "-2", "--format=%an <%ae>|%s").splitlines() == [
        f"{AUTOR}|claude-app: escrever_nota {HORTA}", f"{AUTOR_FOTO}|vault: estado antes de escrever_nota {HORTA}"]
    assert _git(raiz, "show", f"HEAD:{HORTA}") == "# V3\n"


async def test_vault_write_note_append_guarda_antes_a_edicao_do_dono(app, raiz):
    nota = "00-inbox/ideia-bicicleta.md"
    (raiz / nota).write_text("# V2 do dono\n", encoding="utf-8")
    novo = "00-inbox/nao-rastreada.md"
    (raiz / novo).write_text("# Do dono, nunca comitada\n", encoding="utf-8")
    vazio = "00-inbox/vazia-sem-commit.md"
    (raiz / vazio).write_bytes(b"")
    antes = _commits(raiz)
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": nota, "content": "mais\n", "mode": "append"})
        await c.call_tool("vault_write_note", {"path": novo, "content": "mais\n", "mode": "append"})
        await c.call_tool("vault_write_note", {"path": vazio, "content": "# Agora\n", "mode": "append"})
    # 2 fotos + 3 commits: a nota vazia e não rastreada não ganha foto.
    assert _commits(raiz) == antes + 5
    assert _git(raiz, "log", "-5", "--format=%an|%s").splitlines() == [
        f"claude-app|claude-app: vault_write_note {vazio}",
        f"claude-app|claude-app: vault_write_note {novo}", f"vault|vault: estado antes de vault_write_note {novo}",
        f"claude-app|claude-app: vault_write_note {nota}", f"vault|vault: estado antes de vault_write_note {nota}"]
    assert _git(raiz, "show", f"HEAD~4:{nota}") == "# V2 do dono\n"
    assert _git(raiz, "show", f"HEAD~2:{novo}") == "# Do dono, nunca comitada\n"


async def test_nota_sem_mudanca_nao_ganha_foto(app, raiz):
    antes = _commits(raiz)
    async with Client(app) as c:
        lida = await _ler(c, HORTA)
        await c.call_tool("escrever_nota", {"caminho": HORTA, "conteudo": "# Nova\n", "versao": lida["versao"]})
        await c.call_tool("vault_write_note", {"path": HORTA, "content": "+\n", "mode": "append"})
    assert _commits(raiz) == antes + 2
    assert "vault:" not in _git(raiz, "log", "--format=%s")


@pytest.mark.parametrize("como", ["lock", "filtro", "trava"])
async def test_foto_que_falha_recusa_e_nao_muda_o_arquivo(app, raiz, monkeypatch, caplog, como):
    nota = "00-inbox/ideia-bicicleta.md"
    (raiz / HORTA).write_text("# Do dono H\n", encoding="utf-8")
    (raiz / nota).write_text("# Do dono B\n", encoding="utf-8")
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    if como == "lock":
        monkeypatch.setattr(vault_git, "ESPERAS_LOCK", (0.01,))
        (raiz / ".git" / "index.lock").write_bytes(b"")
    elif como == "filtro":
        (raiz / ".gitattributes").write_text("*.md filter=x\n", encoding="utf-8")
    else:
        monkeypatch.setattr(vault_git, "PRAZO_TRAVA", 0.05)
        vault_git._trava_git.acquire()
    antes = _commits(raiz)
    try:
        with caplog.at_level(logging.WARNING, logger="assistente"):
            async with Client(app) as c:
                lida = await _ler(c, HORTA)
                for ferramenta, args in (
                        ("escrever_nota", {"caminho": HORTA, "conteudo": "# IA\n", "versao": lida["versao"]}),
                        ("restaurar_nota", {"caminho": HORTA, "versao_git": inicial}),
                        ("vault_write_note", {"path": nota, "content": "+\n", "mode": "append"}),
                        ("vault_update_frontmatter", {"path": nota, "frontmatter": {"a": 1}})):
                    with pytest.raises(ToolError) as erro:
                        await c.call_tool(ferramenta, args)
                    if como == "trava" and ferramenta == "restaurar_nota":  # a leitura da versão já para
                        assert str(erro.value) == "Não consegui ler o histórico do vault. Nada foi trocado."
                    else:
                        assert str(erro.value) == RECUSA_FOTO, ferramenta
    finally:
        if como == "trava":
            vault_git._trava_git.release()
    (raiz / ".git" / "index.lock").unlink(missing_ok=True)
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Do dono H\n"
    assert (raiz / nota).read_text(encoding="utf-8") == "# Do dono B\n"
    assert CHAMADAS_PECA == []  # a recusa não chega à peça
    assert _commits(raiz) == antes
    assert sum("Foto do vault falhou" in m for m in _avisos(caplog)) == (3 if como == "trava" else 4)


async def test_restaurar_com_nota_mudada_no_meio(app, raiz, monkeypatch):
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).write_text("# Estragada\n", encoding="utf-8")
    _git(raiz, "commit", "-q", "-m", "estraga", "--", HORTA)
    original_foto = vault.foto_ou_recusa

    def _outro_aparelho_escreve(raiz_, rel, ferramenta):
        original_foto(raiz_, rel, ferramenta)
        (raiz / HORTA).write_text("# Do celular, agora\n", encoding="utf-8")

    monkeypatch.setattr(vault, "foto_ou_recusa", _outro_aparelho_escreve)
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial})
    assert str(erro.value) == vault.RESTAURAR_MUDOU
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Do celular, agora\n"


async def test_restaurar_com_nota_criada_no_meio(app, raiz, monkeypatch):
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).unlink()
    original = vault.gravar_nota

    def _criada_antes(raiz_, caminho, conteudo, versao):
        (raiz / HORTA).write_text("# Criada no Mac\n", encoding="utf-8")
        return original(raiz_, caminho, conteudo, versao)

    monkeypatch.setattr(vault, "gravar_nota", _criada_antes)
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial})
    assert str(erro.value) == vault.RESTAURAR_MUDOU
    assert (raiz / HORTA).read_text(encoding="utf-8") == "# Criada no Mac\n"


@pytest.mark.parametrize("atual", [b"caf\xe9 latin1\n", ("x" * (vault.LIMITE_CONTEUDO + 1)).encode()])
async def test_restaurar_com_nota_atual_nao_trocavel(app, raiz, atual):
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).write_bytes(atual)
    antes = _commits(raiz)
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": inicial})
    assert str(erro.value) == vault.RESTAURAR_NAO_TROCAVEL
    assert (raiz / HORTA).read_bytes() == atual
    assert _commits(raiz) == antes


# ---- timeout do git: SIGTERM antes do SIGKILL ----

def test_timeout_manda_sigterm_e_o_git_apaga_o_lock(raiz, monkeypatch):
    lock = _git_falso(raiz.parent, monkeypatch,
                      'trap \'rm -f "$LOCK_FALSO"; exit 143\' TERM\n: > "$LOCK_FALSO"\nsleep 30 &\nwait')
    monkeypatch.setattr(vault_git, "TIMEOUT_ESCRITA", 0.5)
    inicio = time.monotonic()
    with pytest.raises(vault_git.ErroGit, match=r"git add passou de 0.5 s"):
        vault_git._git(raiz, "add", "--", "x.md")
    assert time.monotonic() - inicio < 4
    assert not lock.exists()  # o SIGTERM deixou o git apagar o lock


def test_git_que_ignora_sigterm_leva_sigkill(raiz, monkeypatch):
    lock = _git_falso(raiz.parent, monkeypatch, 'trap "" TERM\n: > "$LOCK_FALSO"\nsleep 30')
    monkeypatch.setattr(vault_git, "TIMEOUT_ESCRITA", 0.3)
    monkeypatch.setattr(vault_git, "ESPERA_TERMINO", 0.3)
    inicio = time.monotonic()
    with pytest.raises(vault_git.ErroGit, match="git commit passou de 0.3 s"):
        vault_git._git(raiz, "commit", "-m", "x")
    assert time.monotonic() - inicio < 4
    assert lock.exists()  # só o SIGKILL: o lock fica (o lint diário avisa)


def test_timeout_de_leitura_e_de_escrita():
    assert (vault_git.TIMEOUT_ESCRITA, vault_git.TIMEOUT_LEITURA, vault_git.ESPERA_TERMINO) == (60, 15, 5)
    assert vault_git.SUBCOMANDOS_ESCRITA == {"add", "commit"}


def test_leitura_usa_o_timeout_curto(raiz, monkeypatch):
    _git_falso(raiz.parent, monkeypatch, "sleep 30 & wait")
    monkeypatch.setattr(vault_git, "TIMEOUT_LEITURA", 0.3)
    for sub in ("log", "cat-file", "ls-tree", "rev-parse", "diff"):
        with pytest.raises(vault_git.ErroGit, match=f"git {sub} passou de 0.3 s"):
            vault_git._git(raiz, sub)


# ---- config do repositório que rodaria comando ----

def _marca(pasta: Path, nome: str) -> tuple[Path, Path]:
    """Script que cria um arquivo-marca e repassa a entrada (serve de filtro clean); devolve (script, marca)."""
    marca = pasta / f"marca-{nome}"
    script = pasta / f"roda-{nome}.sh"
    script.write_text(f'#!/bin/sh\n: > "{marca}"\ncat\n', encoding="utf-8")
    script.chmod(0o755)
    return script, marca


def test_config_do_repositorio_nao_roda_comando(raiz, tmp_path, monkeypatch):
    marcas = []
    with open(raiz / ".git" / "config", "a", encoding="utf-8") as f:
        for chave in ("core.fsmonitor", "diff.external", "core.sshCommand", "core.pager", "gpg.program"):
            script, marca = _marca(tmp_path, chave)
            marcas.append(marca)
            secao, nome = chave.split(".")
            f.write(f"[{secao}]\n\t{nome} = {script}\n")
        script, marca = _marca(tmp_path, "filtro")
        marcas.append(marca)
        f.write(f"[filter \"x\"]\n\tclean = {script}\n\tsmudge = {script}\n")
        ganchos = tmp_path / "ganchos"
        ganchos.mkdir()
        for gancho in ("pre-commit", "post-commit", "commit-msg", "post-index-change"):
            script, marca = _marca(tmp_path, gancho)
            marcas.append(marca)
            shutil.copy(script, ganchos / gancho)
        f.write(f"[core]\n\thooksPath = {ganchos}\n[commit]\n\tgpgsign = true\n")
    # Config global do usuário também não vale.
    casa = tmp_path / "casa"
    casa.mkdir()
    script, marca = _marca(tmp_path, "global")
    marcas.append(marca)
    (casa / ".gitconfig").write_text(f"[core]\n\tfsmonitor = {script}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(casa / ".config"))
    (raiz / HORTA).write_text("# Mudou\n", encoding="utf-8")
    assert vault_git.commitar(raiz, HORTA, "claude-app: teste") is True
    assert vault_git.historico(raiz, HORTA)[0]["mensagem"] == "claude-app: teste"
    vault_git.conteudo_em(raiz, HORTA, _git(raiz, "rev-parse", "HEAD").strip())
    assert [m.name for m in marcas if m.exists()] == []


def test_filtro_no_gitattributes_nao_comita_e_avisa(raiz, tmp_path, caplog):
    script, marca = _marca(tmp_path, "filtro")
    with open(raiz / ".git" / "config", "a", encoding="utf-8") as f:
        f.write(f"[filter \"x\"]\n\tclean = {script}\n")
    (raiz / ".gitattributes").write_text("*.md filter=x\n", encoding="utf-8")
    (raiz / HORTA).write_text("# Mudou\n", encoding="utf-8")
    antes = _commits(raiz)
    with caplog.at_level(logging.WARNING, logger="assistente"):
        assert vault_git.commitar(raiz, HORTA, "claude-app: teste") is False
    assert not marca.exists()
    assert _commits(raiz) == antes
    assert _avisos(caplog) == [f"Commit do vault falhou em {HORTA} (o .gitattributes põe filter neste caminho e o "
                               "filtro rodaria comando); a escrita vale"]


# ---- trava do git com prazo ----

def test_trava_ocupada_pula_o_commit_com_aviso(raiz, monkeypatch, caplog):
    monkeypatch.setattr(vault_git, "PRAZO_TRAVA", 0.05)
    (raiz / "00-inbox/t.md").write_text("# T\n", encoding="utf-8")
    antes = _commits(raiz)
    vault_git._trava_git.acquire()
    try:
        with caplog.at_level(logging.WARNING, logger="assistente"):
            assert vault_git.commitar(raiz, "00-inbox/t.md", "m") is False
    finally:
        vault_git._trava_git.release()
    assert _avisos(caplog) == ["Commit do vault falhou em 00-inbox/t.md (trava do git ocupada há 0.05 s); "
                               "a escrita vale"]
    assert _commits(raiz) == antes


# ---- caminhos do mcpvault no commit ----

@pytest.mark.parametrize("path,comitado", [
    ("/00-inbox/barra.md", "00-inbox/barra.md"),
    ("  00-inbox/espaco.md  ", "00-inbox/espaco.md"),
    ("00-inbox/t.txt", "00-inbox/t.txt"),
    ("00-inbox/c.canvas", "00-inbox/c.canvas"),
    ("00-inbox/b.base", "00-inbox/b.base"),
    ("00-inbox/m.markdown", "00-inbox/m.markdown"),
    ("00-inbox/maiuscula.MD", "00-inbox/maiuscula.MD"),
])
async def test_escrita_do_mcpvault_com_caminho_do_jeito_dele_comita(app, raiz, path, comitado):
    antes = _commits(raiz)
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": path, "content": "# x\n", "mode": "append"})
    assert _commits(raiz) == antes + 1
    assert _ultimo(raiz) == (AUTOR, f"claude-app: vault_write_note {comitado}", [comitado])


async def test_caminho_absoluto_com_a_raiz_comita(app, raiz):
    path = f"{os.path.realpath(raiz)}/00-inbox/absoluto.md"
    async with Client(app) as c:
        await c.call_tool("vault_write_note", {"path": path, "content": "# x\n", "mode": "append"})
    assert _ultimo(raiz)[2] == ["00-inbox/absoluto.md"]


@pytest.mark.parametrize("ruim", ["00-inbox/../00-inbox/x.md", "../fora.md", ".git/x.md", ".Git/x.md",
                                  "a/.obsidian/x.md", ".stversions/x.md", ".trash/x.md", ".git./x.md",
                                  "00-inbox/sem-extensao", "00-inbox/x.sh", "", "/", 3, None])
def test_relativo_para_commit_recusa(raiz, ruim):
    assert vault.relativo_para_commit(raiz, ruim) is None


def test_relativo_para_commit_recusa_link_para_fora_ou_para_o_git(raiz, tmp_path):
    (tmp_path / "fora.md").write_text("x", encoding="utf-8")
    (raiz / "00-inbox/link-fora.md").symlink_to(tmp_path / "fora.md")
    (raiz / "00-inbox/link-git.md").symlink_to(raiz / ".git" / "config")
    assert vault.relativo_para_commit(raiz, "00-inbox/link-fora.md") is None
    assert vault.relativo_para_commit(raiz, "00-inbox/link-git.md") is None


def test_relativo_para_commit_tenta_nfc_e_nfd(raiz, monkeypatch):
    nfd = unicodedata.normalize("NFD", "00-inbox/ação.md")
    nfc = unicodedata.normalize("NFC", nfd)
    (raiz / nfd).write_text("# x\n", encoding="utf-8")
    nomes = {nfd}

    # Sistema de arquivos que distingue NFC de NFD (ext4 do i7): só o nome exato existe.
    def _lexists(p):
        rel = os.path.relpath(p, os.path.realpath(raiz))
        return rel in nomes or (not rel.endswith(".md") and os.path.isdir(p))

    monkeypatch.setattr(vault.os.path, "lexists", _lexists)
    assert vault.relativo_para_commit(raiz, nfc) == nfd
    assert vault.relativo_para_commit(raiz, nfd) == nfd


async def test_escrita_sem_commit_por_caminho_avisa_sem_conteudo(app, raiz, caplog):
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("vault_write_note", {"path": "00-inbox/sem-extensao", "content": SEGREDO,
                                                   "mode": "append"})
    assert _avisos(caplog) == ["Escrita sem commit em vault_write_note: caminho que o commit não aceita "
                               "(o commit diário decide)"]
    assert SEGREDO not in caplog.text


# ---- histórico com o caminho de cada versão ----

async def test_historico_traz_o_caminho_de_cada_versao_e_se_restaura(app, raiz):
    novo = "10-projetos/horta.md"
    _git(raiz, "mv", HORTA, novo)
    _git(raiz, "commit", "-q", "-m", "renomeia")
    async with Client(app) as c:
        h = (await c.call_tool("historico_nota", {"caminho": novo})).data
        descricao = {t.name: t for t in await c.list_tools()}["historico_nota"].description
        with pytest.raises(ToolError, match="restauravel"):
            await c.call_tool("restaurar_nota", {"caminho": novo, "versao_git": h[1]["versao_git"]})
    assert [(v["mensagem"], v["caminho"], v["restauravel"]) for v in h] == [
        ("renomeia", novo, True), ("inicial", HORTA, False)]
    assert "caminho" in descricao and "restauravel" in descricao
