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
from fastmcp import Client, FastMCP
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
    # Achado 3 do revisor (Passo 5): a chave do pai vale para item de lista e dict aninhado; senha em texto comum.
    ({"frontmatter": {"password": [SENHA]}}, "cabecalho_auth"),
    ({"frontmatter": {"api_key": {"v": SENHA}}}, "cabecalho_auth"),
    ({"frontmatter": {"senha": [{"banco": SENHA}]}}, "cabecalho_auth"),
    ({"frontmatter": {"senha": 98213377}}, "senha"),
    ({"conteudo": f"A senha do banco é {SENHA}"}, "senha"),
    ({"conteudo": f"Senha do banco: {SENHA}"}, "senha"),
    ({"conteudo": f"**Senha:** {SENHA}"}, "senha"),
    ({"conteudo": f"senha: `{SENHA}`"}, "senha"),
    ({"conteudo": f"| conta | senha |\n|---|---|\n| banco | senha | {SENHA} |"}, "senha"),
    ({"conteudo": f"pwd: {SENHA}"}, "senha"),
    ({"conteudo": f"pass: {SENHA}"}, "senha"),
    ({"conteudo": "senha: 12345678"}, "senha"),
    ({"conteudo": "password: {{segredo:a}}" + SENHA}, "cabecalho_auth"),
])
def test_acha_segredo_em_texto_dict_e_lista(argumentos, tipo):
    assert segredos_mcp.segredo_nos_argumentos(argumentos) == tipo


@pytest.mark.parametrize("argumentos", [
    {"conteudo": "senha do roteador: {{segredo:roteador}}"},
    {"frontmatter": {"password": "{{segredo:wifi}}", "tags": ["projeto", "senha"]}},
    {"frontmatter": {"senha": "trocar-amanha", "token": "obrigatorio"}},
    {"valor": 42.9, "id": 3, "ok": True, "nada": None},
    {"conteudo": "a senha é forte; a senha do wifi está no cofre"},
    {"conteudo": "senha: {{segredo:wifi}}\npassword: obrigatório\nSenha: ver no Vaultwarden\npin: 1234"},
    {"frontmatter": {"password": ["{{segredo:wifi}}"], "tags": ["senha", "token"], "pin": 1234}},
    {"frontmatter": {"credentials": "~/.config/gcloud/application_default_credentials.json"}},
    {"conteudo": "DATABASE_URL: postgresql+psycopg://app:${DB_PASS}@db:5432/app"},
    # Revisor final da Sprint 2b: texto comum com acento, data no PIN, "resenha" e frase entre aspas.
    {"conteudo": "Troquei a senha do Itaú: Atualização feita no app.\n| Banco | Senha | Situação |\n"
                 "Senha do Netflix: Anotação na agenda\nA senha nova é Provisória até sexta\n"
                 "Pass: Bilhete-Único-Mensal\npin: 20261022\nResenha: Duna-2021\n"
                 'resenha: "Ótimo livro, recomendo"\nsenha: "ver no Bitwarden"\n'},
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


def test_limite_de_caracteres():
    assert segredos_mcp.CARACTERES_MAXIMOS == 400_000


def test_conferencia_no_limite_e_rapida():
    """Achado 4 do revisor (Passo 5): 400.000 caracteres hostis não seguram a thread (antes, 1 MB de '-' levava ~6 s)."""
    import time

    for unidade in ("-", "a-_ =:", "senha ", "curl "):
        texto = (unidade * (segredos_mcp.CARACTERES_MAXIMOS // len(unidade)))[:segredos_mcp.CARACTERES_MAXIMOS - 20]
        inicio = time.perf_counter()
        assert segredos_mcp.segredo_nos_argumentos({"c": texto}) is None
        assert time.perf_counter() - inicio < 2.0


def test_quem_passa_pela_barreira():
    """Falha fechado (achado 9 do revisor, Passo 5): vigia tudo que não é leitura conhecida, menos `paperless_*`."""
    b = segredos_mcp.BarreiraSegredo({"ler_nota", "vault_read_note"})
    assert b._vigia("escrever_nota") and b._vigia("vault_write_note") and b._vigia("0123456789ab_vault_write_note")
    assert b._vigia("ferramenta_nova") and b._vigia("vault_nova") and b._vigia(None)
    assert not b._vigia("ler_nota") and not b._vigia("0123456789ab_ler_nota") and not b._vigia("vault_read_note")
    # Paperless fica de fora por decisão (Ficha 5 fala de vault e banco).
    assert not b._vigia("paperless_update_document") and not b._vigia("0123456789ab_paperless_create_tag")
    app_b = segredos_mcp.BarreiraSegredo(servidor.LEITURAS_PECAS | servidor.LEITURAS_BANCO | vault.LEITURAS_VAULT)
    for nome in servidor.ESCRITAS_PECAS_VAULT | servidor.ESCRITAS_BANCO | vault.ESCRITAS_VAULT:
        assert app_b._vigia(nome), nome


def test_registro_redige_caminho_e_descarta_modelo_com_cara_de_segredo():
    assert registro.caminhos_do_vault({"path": f"00-inbox/{AWS}.md"}) == {"caminho": "[segredo:aws]"}
    assert registro.caminhos_do_vault({"path": "00-inbox/nota.md"}) == {"caminho": "00-inbox/nota.md"}
    assert registro.modelo_declarado(AWS) is None
    assert registro.modelo_declarado("claude-opus-5-5") == "claude-opus-5-5"


def test_registro_nao_grava_pedaco_de_segredo_que_o_corte_esconderia():
    """Achado 10 do revisor (Passo 5): o segredo só é reconhecido com o fim (aspa que fecha depois do corte).

    Antes, `tirar_segredos` olhava os 600 primeiros caracteres, não reconhecia, e os 300 primeiros iam para a
    auditoria com o começo do segredo.
    """
    pedaco = "Tr0caEst@99 "
    caminho = 'n/TOKEN="' + pedaco * 60 + '".md'
    assert segredos.achar_segredo(caminho) == "variavel_segredo"
    dados = registro.caminhos_do_vault({"path": caminho, "paths": [caminho, "ok.md"]})
    assert dados == {"caminho": "[segredo:variavel_segredo]", "caminhos": ["[segredo:variavel_segredo]", "ok.md"]}
    assert registro.caminhos_do_vault({"path": "a" * 20_000}) == {"caminho": registro.CAMINHO_LONGO}
    assert registro.caminhos_do_vault({"path": "a" * 400}) == {"caminho": "a" * registro.TAMANHO_CAMINHO}


# ---------------- barreira no app: banco ----------------

ESCRITAS_BANCO = [
    ("registrar_gasto", {"valor": "10.5", "descricao": f"assinatura {AWS}", "categoria": "lazer"}, "aws"),
    ("registrar_ponto", {"tipo": "entrada", "observacao": f"export GITHUB_TOKEN={GITHUB}"}, "github"),
    ("registrar_atividade", {"descricao": "estudo", "tags": ["ok", AWS]}, "aws"),
    ("desfazer_registro", {"tipo": "gasto", "id": 1, "modelo": AWS}, "aws"),
    ("vincular_nota", {"tipo": "gasto", "id": 1, "caminho": f"00-inbox/{AWS}.md"}, "aws"),
    ("marcar_desatualizada", {"caminho": HORTA, "motivo": f"tem password={SENHA}"}, "cabecalho_auth"),
    ("conferir_gastos", {"itens": [{"id": 1, "categoria": f"lazer {AWS}"}]}, "aws"),
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
    ("restaurar_nota", {"caminho": f"00-inbox/{AWS}.md", "versao_git": "abcdef1"}, "aws", "[segredo:aws]"),
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


async def test_escrita_nova_fora_das_listas_passa_pela_barreira(app, raiz, url):  # noqa: F811
    """Achado 9 do revisor (Passo 5): ferramenta montada sem entrar em lista nenhuma é vigiada (falha fechado)."""
    chamadas: list[str] = []
    nova = FastMCP("nova")

    @nova.tool
    def anotar_coisa(texto: str) -> str:
        chamadas.append(texto)
        return "ok"

    app.mount(nova)
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("anotar_coisa", {"texto": f"chave {AWS}"})
        assert str(erro.value) == _msg("aws")
        assert chamadas == []
        assert (await c.call_tool("anotar_coisa", {"texto": "texto comum"})).data == "ok"
    assert chamadas == ["texto comum"]
    _sem_valor(url, str(erro.value))


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


async def test_patch_nao_confere_o_old_string(app, raiz, url):  # noqa: F811
    """Revisor final da Sprint 2b: o oldString já está no disco (a nota do dono); só o newString entra no vault.

    Conferir o oldString recusaria tirar um segredo da nota pelo app. A peça falsa recebe a chamada e devolve o erro
    dela (não a recusa da barreira); com o segredo no newString, a barreira recusa.
    """
    async with Client(app) as c:
        with pytest.raises(ToolError) as erro:
            await c.call_tool("vault_patch_note", {"path": HORTA, "oldString": f"chave {AWS}",
                                                   "newString": "chave no cofre: {{segredo:aws}}"})
        assert "oldString não encontrado" in str(erro.value)
        with pytest.raises(ToolError) as erro:
            await c.call_tool("0123456789ab_vault_patch_note", {"path": HORTA, "oldString": "Horta",
                                                                "newString": f"chave {AWS}"})
        assert str(erro.value) == _msg("aws")
        with pytest.raises(ToolError) as erro:
            await c.call_tool("vault_patch_note", {"path": HORTA, "oldString": "Horta", "newString": f"chave {AWS}"})
        assert str(erro.value) == _msg("aws")
    _sem_valor(url, str(erro.value))


def test_barreira_tira_so_o_old_string_do_patch():
    barreira = segredos_mcp.BarreiraSegredo(set())
    argumentos = {"path": "a.md", "oldString": f"chave {AWS}", "newString": "x"}
    assert barreira._conferidos("vault_patch_note", argumentos) == {"path": "a.md", "newString": "x"}
    assert barreira._conferidos("0123456789ab_vault_patch_note", argumentos) == {"path": "a.md", "newString": "x"}
    assert barreira._conferidos("vault_write_note", argumentos) == argumentos  # só o patch
    assert argumentos["oldString"] == f"chave {AWS}"  # não muda os argumentos da chamada


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


def test_arquivo_grande_demais_fica_sem_commit_e_sem_foto(raiz, caplog, monkeypatch):  # noqa: F811
    """Achado 4 do revisor (Passo 5): acima de 1 MB, não confere (travaria a thread): sem commit, e a foto recusa."""
    monkeypatch.setattr(vault_git, "LIMITE_CONFERIR", 1_000)
    (raiz / "00-inbox/grande.md").write_text("texto comum\n" * 200, encoding="utf-8")
    commits = _commits(raiz)
    with caplog.at_level(logging.DEBUG, logger="assistente"):
        assert vault_git.commitar(raiz, "00-inbox/grande.md", "claude-app: teste") is False
    assert _commits(raiz) == commits
    assert ("Escrita de 00-inbox/grande.md ficou sem commit: o arquivo passa de 1000 bytes e não dá para conferir "
            "segredo.") in [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    alvo = raiz / HORTA
    alvo.write_text(alvo.read_text(encoding="utf-8") + "linha comum\n" * 200, encoding="utf-8")
    with pytest.raises(vault_git.FotoFalhou) as erro:
        vault_git.foto(raiz, HORTA, "vault_write_note")
    assert not isinstance(erro.value, vault_git.FotoComSegredo)  # a mensagem é a da foto que falhou (RECUSA_FOTO)
    assert _commits(raiz) == commits
    assert vault_git.LIMITE_CONFERIR == 1_000 and vault_git.GRANDE_DEMAIS == "grande_demais"


def test_limite_de_conferencia_do_arquivo_e_1_mb():
    assert vault_git.LIMITE_CONFERIR == 1_000_000


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
