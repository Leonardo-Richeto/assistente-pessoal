"""Barreira de segredo (Passo 5 da Sprint 2b, 2b.3; Ficha 5, regra 5).

App de verdade (criar_app) sobre uma cópia do vault sintético com git, como em test_vault_git.py. Toda escrita do
banco e do vault com cara de segredo é recusada antes de rodar; a mensagem, o log, o banco e o disco nunca têm o
valor. Commit por escrita e foto pulam arquivo com segredo; restaurar_nota confere o conteúdo que vem do git;
o importador de sessões redige.

As chaves dos testes são inventadas e montadas em partes, para scanner de repositório não acusar o arquivo.
"""

import logging
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import registro, segredos, segredos_mcp, servidor, vault, vault_git
from assistente.modelos import Auditoria, Chamada, Sessao
from test_sessoes import _importar, resumo
from test_vault_git import (CHAMADAS_PECA, HORTA, _commits, _criar_app, _git, _ler, app, raiz,  # noqa: F401
                            url)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="precisa do git do sistema")

AWS = "AKIA" + "Z7QW3RTY9UIO2PLK"
GITHUB = "ghp_" + "Xy9Zq8Wv7Ut6Sr5Qp4On3Ml2Kj1Ih0Gf"
SENHA = "Tr0ca" + "-Est@Senha99"
VALORES = (AWS, GITHUB, SENHA)
CANONICA = Path(__file__).resolve().parents[2] / "ferramentas" / "sessoes" / "segredos.py"


def _msg(tipo: str) -> str:
    return f"Recusei: o texto parece ter um segredo ({tipo}). Guarde o valor no cofre e escreva {{{{segredo:NOME}}}}."


def _disco(raiz: Path) -> dict[str, bytes]:
    """Todo arquivo do vault fora do .git, com os bytes."""
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(raiz).parts}


def _auditoria(url) -> list[Auditoria]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def _chamadas(url) -> list[Chamada]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Chamada).order_by(Chamada.id)))


def _sem_valor(url: str, *textos: str) -> None:
    """Nenhum valor de segredo no arquivo do banco nem nos textos dados (log, mensagem)."""
    banco = Path(url.removeprefix("sqlite:///")).read_bytes()
    for v in VALORES:
        assert v.encode() not in banco
        for t in textos:
            assert v not in t


# ---------------- a cópia do servidor ----------------

def test_copia_igual_a_canonica():
    """servidor/assistente/segredos.py é cópia de ferramentas/sessoes/segredos.py (a imagem só leva servidor/)."""
    if not CANONICA.exists():
        pytest.skip("ferramentas/ não existe (imagem Docker): nada a comparar")
    assert Path(segredos.__file__).read_bytes() == CANONICA.read_bytes(), (
        "As duas cópias de segredos.py divergem: mude as duas juntas (a canônica é ferramentas/sessoes/segredos.py).")


# ---------------- barreira: unidade ----------------

def test_mensagem_de_recusa():
    assert segredos_mcp.mensagem_recusa("aws") == _msg("aws")


@pytest.mark.parametrize("argumentos,tipo", [
    ({"conteudo": f"chave {AWS}"}, "aws"),
    ({"frontmatter": {"password": SENHA}}, "cabecalho_auth"),  # só com a chave junto
    ({"frontmatter": {"conta": {"api_key": SENHA}}}, "cabecalho_auth"),
    ({"tags": ["ok", ["fundo", GITHUB]]}, "github"),
    ({"frontmatter": {AWS: 1}}, "aws"),  # chave do dict também conta
    ({"x": [{"y": [f"Authorization: Bearer {GITHUB[4:]}"]}]}, "bearer"),
])
def test_acha_segredo_em_texto_dict_e_lista(argumentos, tipo):
    assert segredos_mcp.segredo_nos_argumentos(argumentos) == tipo


@pytest.mark.parametrize("argumentos", [
    {"conteudo": "senha do roteador: {{segredo:roteador}}"},
    {"frontmatter": {"password": "{{segredo:wifi}}", "tags": ["projeto", "senha"]}},
    {"frontmatter": {"senha": "trocar-amanha", "token": "obrigatorio"}},
    {"valor": 42.9, "id": 3, "ok": True, "nada": None},
])
def test_referencia_e_texto_comum_passam(argumentos):
    assert segredos_mcp.segredo_nos_argumentos(argumentos) is None


def test_argumentos_grandes_ou_fundos_demais_sao_recusados():
    fundo: list = ["x"]
    for _ in range(segredos_mcp.PROFUNDIDADE_MAXIMA + 2):
        fundo = [fundo]
    with pytest.raises(segredos_mcp.GrandeDemais):
        segredos_mcp.segredo_nos_argumentos({"tags": fundo})
    with pytest.raises(segredos_mcp.GrandeDemais):
        segredos_mcp.segredo_nos_argumentos({"tags": ["a"] * (segredos_mcp.ITENS_MAXIMOS + 1)})
    with pytest.raises(segredos_mcp.GrandeDemais):
        segredos_mcp.segredo_nos_argumentos({"conteudo": "a" * (segredos_mcp.CARACTERES_MAXIMOS + 1)})


def test_quem_passa_pela_barreira():
    b = segredos_mcp.BarreiraSegredo({"escrever_nota", "vault_write_note"})
    assert b._vigia("escrever_nota") and b._vigia("vault_write_note") and b._vigia("0123456789ab_vault_write_note")
    assert not b._vigia("ler_nota") and not b._vigia("0123456789ab_ler_nota") and not b._vigia(None)
    vigiadas = servidor.ESCRITAS_PECAS_VAULT
    assert vigiadas == {"vault_write_note", "vault_patch_note", "vault_update_frontmatter", "vault_manage_tags"}
    assert not {n for n in vigiadas if n.startswith("paperless_")}  # Paperless fica de fora (Ficha 5 fala de vault e banco)


def test_registro_redige_caminho_e_descarta_modelo_com_cara_de_segredo():
    assert registro.caminhos_do_vault({"path": f"00-inbox/{AWS}.md"}) == {"caminho": "00-inbox/[segredo:aws].md"}
    assert registro.modelo_declarado(AWS) is None
    assert registro.modelo_declarado("claude-opus-5-5") == "claude-opus-5-5"


# ---------------- barreira no app: banco ----------------

ESCRITAS_BANCO = [
    ("registrar_gasto", {"valor": "10.5", "descricao": f"assinatura {AWS}", "categoria": "lazer"}, "aws"),
    ("registrar_ponto", {"tipo": "entrada", "observacao": f"export GITHUB_TOKEN={GITHUB}"}, "github"),
    ("registrar_atividade", {"descricao": "estudo", "tags": ["ok", AWS]}, "aws"),
    ("desfazer_registro", {"tipo": "gasto", "id": 1, "modelo": AWS}, "aws"),
    ("vincular_nota", {"tipo": "gasto", "id": 1, "caminho": f"00-inbox/{AWS}.md"}, "aws"),
    ("marcar_desatualizada", {"caminho": HORTA, "motivo": f"tem password={SENHA}"}, "cabecalho_auth"),
]


def test_toda_escrita_do_banco_esta_nos_testes():
    assert {n for n, _, _ in ESCRITAS_BANCO} == servidor.ESCRITAS_BANCO


@pytest.mark.parametrize("nome,argumentos,tipo", ESCRITAS_BANCO, ids=[n for n, _, _ in ESCRITAS_BANCO])
async def test_escrita_do_banco_com_segredo_e_recusada(app, url, caplog, nome, argumentos, tipo):  # noqa: F811
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            with pytest.raises(ToolError) as erro:
                await c.call_tool(nome, argumentos)
    assert str(erro.value) == _msg(tipo)
    assert _auditoria(url) == []  # nada gravado (as escritas do banco só auditam o que gravam)
    assert [(ch.ferramenta, ch.resultado, ch.modelo_declarado) for ch in _chamadas(url)] == [(nome, "erro", None)]
    _sem_valor(url, str(erro.value), caplog.text)


async def test_escrita_do_banco_com_referencia_passa(app, url):  # noqa: F811
    async with Client(app) as c:
        r = (await c.call_tool("registrar_atividade", {"descricao": "senha do wifi em {{segredo:wifi}}",
                                                       "tags": ["casa"]})).data
    assert r["confirmacao"].endswith("Desfazer?")
    assert [(a.ferramenta, a.acao) for a in _auditoria(url)] == [("registrar_atividade", "criar")]


# ---------------- barreira no app: vault ----------------

ESCRITAS_VAULT = [
    ("escrever_nota", {"caminho": "00-inbox/nova.md", "conteudo": f"# Nova\n\nchave {AWS}\n", "versao": "nova"},
     "aws", "00-inbox/nova.md"),
    ("restaurar_nota", {"caminho": f"00-inbox/{AWS}.md", "versao_git": "abcdef1"}, "aws",
     "00-inbox/[segredo:aws].md"),
    ("vault_write_note", {"path": HORTA, "mode": "append", "content": "linha comum\n",
                          "frontmatter": {"password": SENHA}}, "cabecalho_auth", HORTA),
    ("vault_write_note", {"path": HORTA, "mode": "append", "content": "linha comum\n",
                          "frontmatter": {"conta": {"api_key": SENHA}}}, "cabecalho_auth", HORTA),
    ("vault_patch_note", {"path": HORTA, "oldString": "Horta", "newString": f"Authorization: Bearer {GITHUB[4:]}"},
     "bearer", HORTA),
    ("vault_update_frontmatter", {"path": HORTA, "frontmatter": {"tags": ["horta", GITHUB]}}, "github", HORTA),
    ("vault_manage_tags", {"path": HORTA, "operation": "add", "tags": ["ok", AWS]}, "aws", HORTA),
]


def test_toda_escrita_do_vault_esta_nos_testes():
    nomes = {n for n, *_ in ESCRITAS_VAULT}
    assert nomes == servidor.ESCRITAS_PECAS_VAULT | vault.ESCRITAS_VAULT


@pytest.mark.parametrize("nome,argumentos,tipo,caminho", ESCRITAS_VAULT,
                         ids=[f"{n}-{i}" for i, (n, *_) in enumerate(ESCRITAS_VAULT)])
async def test_escrita_do_vault_com_segredo_e_recusada(app, raiz, url, caplog, nome, argumentos, tipo,  # noqa: F811
                                                       caminho):
    # O dono mudou a nota sem commit: a barreira vem antes da foto, então nem a foto acontece.
    (raiz / HORTA).write_text((raiz / HORTA).read_text(encoding="utf-8") + "\nedição do dono\n", encoding="utf-8")
    antes, commits = _disco(raiz), _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            with pytest.raises(ToolError) as erro:
                await c.call_tool(nome, argumentos)
    assert str(erro.value) == _msg(tipo)
    assert _disco(raiz) == antes and _commits(raiz) == commits and CHAMADAS_PECA == []
    linhas = _auditoria(url)
    assert [(a.ferramenta, a.tabela, a.acao, a.dados) for a in linhas] == [
        (nome, "vault", "escrever", {"caminho": caminho}), (nome, "vault", "erro", {"caminho": caminho})]
    assert [(ch.ferramenta, ch.resultado) for ch in _chamadas(url)] == [(nome, "erro")]
    _sem_valor(url, str(erro.value), caplog.text)


async def test_nome_com_hash_tambem_passa_pela_barreira(app, raiz, url):  # noqa: F811
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("0123456789ab_vault_write_note", {"path": HORTA, "mode": "append", "content": AWS})
    assert str(erro.value) == _msg("aws")  # a barreira recusa antes de o FastMCP procurar o nome
    assert CHAMADAS_PECA == []


async def test_argumentos_fundos_demais_sao_recusados_no_app(app, raiz):  # noqa: F811
    fundo: list = ["x"]
    for _ in range(segredos_mcp.PROFUNDIDADE_MAXIMA + 2):
        fundo = [fundo]
    antes = _disco(raiz)
    async with Client(app) as c:
        with pytest.raises(ToolError, match="grandes demais para eu conferir"):
            await c.call_tool("vault_update_frontmatter", {"path": HORTA, "frontmatter": {"x": fundo}})
    assert _disco(raiz) == antes


async def test_escrita_do_vault_com_referencia_passa(app, raiz, url):  # noqa: F811
    async with Client(app) as c:
        r = (await c.call_tool("escrever_nota", {"caminho": "00-inbox/roteador.md", "versao": "nova",
                                                 "conteudo": "# Roteador\n\nSenha: {{segredo:roteador}}\n"})).data
        assert r["confirmacao"] == "Criei 00-inbox/roteador.md."
        await c.call_tool("vault_write_note", {"path": HORTA, "mode": "append", "content": "token: {{segredo:x}}\n",
                                               "frontmatter": {"password": "{{segredo:wifi}}"}})
    assert "{{segredo:roteador}}" in (raiz / "00-inbox/roteador.md").read_text(encoding="utf-8")
    assert _git(raiz, "status", "--porcelain").strip() == ""  # as duas viraram commit


# ---------------- commit por escrita e foto ----------------

def _comitar_segredo(raiz: Path, caminho: str = HORTA) -> None:
    """O segredo já está no HEAD (entrou antes da barreira); o disco fica igual ao HEAD."""
    alvo = raiz / caminho
    alvo.write_text(alvo.read_text(encoding="utf-8") + f"\nchave antiga {AWS}\n", encoding="utf-8")
    _git(raiz, "add", "--", caminho)
    _git(raiz, "commit", "-q", "-m", "antes da barreira")


async def test_commit_por_escrita_pula_arquivo_com_segredo(app, raiz, url, caplog):  # noqa: F811
    _comitar_segredo(raiz)
    commits = _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            await c.call_tool("vault_write_note", {"path": HORTA, "mode": "append", "content": "linha comum\n"})
    assert (raiz / HORTA).read_text(encoding="utf-8").endswith("linha comum\n")  # a escrita vale
    assert _commits(raiz) == commits  # sem commit
    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert f"Escrita de {HORTA} ficou sem commit: o arquivo tem algo com cara de segredo." in avisos
    assert [a.acao for a in _auditoria(url)] == ["escrever", "ok"]
    _sem_valor(url, caplog.text)


def test_commitar_direto_pula_arquivo_com_segredo(raiz, caplog):  # noqa: F811
    (raiz / "00-inbox/nova.md").write_text(f"# Nova\n\n{GITHUB}\n", encoding="utf-8")
    commits = _commits(raiz)
    assert vault_git.commitar(raiz, "00-inbox/nova.md", "claude-app: teste") is False
    assert _commits(raiz) == commits
    assert _git(raiz, "ls-files", "--", "00-inbox/nova.md").strip() == ""  # nem foi para o index
    assert GITHUB not in caplog.text


@pytest.mark.parametrize("nome,argumentos", [
    ("vault_write_note", {"path": HORTA, "mode": "append", "content": "linha comum\n"}),
    ("escrever_nota", {"caminho": HORTA, "conteudo": "# Horta\n\nnovo\n"}),
    ("restaurar_nota", {"caminho": HORTA}),
])
async def test_foto_de_nota_com_segredo_recusa_a_escrita(app, raiz, url, caplog, nome, argumentos):  # noqa: F811
    inicial = _git(raiz, "rev-parse", "HEAD").strip()
    # O dono pôs um segredo na nota no Obsidian, sem commit. A IA não pode trocar (a foto não sai).
    alvo = raiz / HORTA
    alvo.write_text(alvo.read_text(encoding="utf-8") + f"\nchave {AWS}\n", encoding="utf-8")
    async with Client(app) as c:
        if nome == "escrever_nota":
            argumentos = {**argumentos, "versao": vault.versao_de(alvo.read_bytes())}
        if nome == "restaurar_nota":
            argumentos = {**argumentos, "versao_git": inicial}
        antes, commits = _disco(raiz), _commits(raiz)
        with caplog.at_level(logging.DEBUG, logger="assistente"):
            with pytest.raises(ToolError) as erro:
                await c.call_tool(nome, argumentos)
    assert str(erro.value) == vault.RECUSA_FOTO_SEGREDO == (
        "A nota tem algo com cara de segredo; não guardo isso no histórico. Tire o segredo no Obsidian e tente de novo.")
    assert _disco(raiz) == antes and _commits(raiz) == commits and CHAMADAS_PECA == []
    assert [a.acao for a in _auditoria(url)] == ["escrever", "erro"]
    _sem_valor(url, caplog.text)


async def test_restaurar_versao_com_segredo_e_recusado(app, raiz, url, caplog):  # noqa: F811
    _comitar_segredo(raiz)
    com_segredo = _git(raiz, "rev-parse", "HEAD").strip()
    (raiz / HORTA).write_text("# Horta\n\nlimpa\n", encoding="utf-8")
    _git(raiz, "commit", "-q", "-am", "tirei o segredo")
    antes, commits = _disco(raiz), _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        async with Client(app) as c:
            with pytest.raises(ToolError) as erro:
                await c.call_tool("restaurar_nota", {"caminho": HORTA, "versao_git": com_segredo})
    assert str(erro.value) == _msg("aws")
    assert _disco(raiz) == antes and _commits(raiz) == commits
    assert [a.acao for a in _auditoria(url)] == ["escrever", "erro"]
    _sem_valor(url, str(erro.value), caplog.text)


# ---------------- importador de sessões ----------------

def test_importador_tira_segredos_antes_de_gravar(url):  # noqa: F811
    r = _importar(url, resumo(titulo=f"usa a chave {AWS} no deploy", arquivos=[f"tmp/{AWS}.txt", "ok.py"],
                              comandos=[f"export GITHUB_TOKEN={GITHUB}", "git status"],
                              commits=[{"id": "1a2b3c4", "mensagem": f"troca token {GITHUB}"}]))
    assert r["aceitas"] == ["aaaaaaaa-0001"]
    with Session(create_engine(url)) as s:
        (sessao,) = s.scalars(select(Sessao)).all()
    assert sessao.titulo == "usa a chave [segredo:aws] no deploy"
    assert sessao.arquivos == ["tmp/[segredo:aws].txt", "ok.py"]
    assert sessao.comandos[1] == "git status" and "[segredo:" in sessao.comandos[0]
    assert sessao.commits == [{"id": "1a2b3c4", "mensagem": "troca token [segredo:github]"}]
    _sem_valor(url)
