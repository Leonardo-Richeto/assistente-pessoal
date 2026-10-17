"""BLOQUEADAS só tem nomes reais e eles somem do endpoint montado.

As peças prontas (mcpvault e paperless-mcp) são processos externos que só existem
na imagem. Aqui elas viram servidores falsos em memória com os nomes reais
capturados da versão fixada (fixtures/ferramentas_pecas.json; como regenerar está
em fixtures/gerar_ferramentas_pecas.py). Sem rede, sem Docker, sem Paperless.
"""

import json
import re
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from assistente import servidor
from assistente.config import Config

AQUI = Path(__file__).parent
PECAS = json.loads((AQUI / "fixtures" / "ferramentas_pecas.json").read_text())
DOCKERFILE = (AQUI.parent / "Dockerfile").read_text()

# namespace usado em criar_app → (peça na fixture, binário que o proxy chama)
NAMESPACES = {"vault": ("mcpvault", "mcpvault"), "paperless": ("paperless-mcp", "paperless-mcp")}

ESSENCIAIS = {
    "consultar_gastos", "registrar_gasto", "desfazer_registro",
    "vault_read_note", "vault_search_notes", "vault_list_directory", "vault_write_note",
    "paperless_search_documents", "paperless_get_document", "paperless_get_document_content",
}
# Nunca podem aparecer, com qualquer conteúdo de BLOQUEADAS.
PROIBIDAS = {
    "vault_delete_note", "vault_move_file", "vault_move_note",
    "paperless_create_share_link", "paperless_delete_document", "paperless_empty_trash",
    "paperless_bulk_edit_documents",
}


def _nomes_reais() -> set[str]:
    return {f"{ns}_{n}" for ns, (peca, _) in NAMESPACES.items() for n in PECAS[peca]["ferramentas"]}


def _proxy_falso(config: dict) -> FastMCP:
    """Substitui create_proxy: devolve a peça com as ferramentas reais, sem subir processo."""
    (ns, alvo), = config["mcpServers"].items()
    peca, binario = NAMESPACES[ns]
    assert alvo["command"] == binario
    falso = FastMCP(peca)

    def _ok() -> str:
        return "ok"

    for nome in PECAS[peca]["ferramentas"]:
        falso.tool(_ok, name=nome)
    return falso


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "create_proxy", _proxy_falso)
    url = f"sqlite:///{tmp_path / 'teste.db'}"
    cfg = Config(_env_file=None, database_url_leitura=url, database_url_escrita=url, auth_desativada=True,
                 vault_path=str(tmp_path), paperless_url="http://127.0.0.1:1", paperless_api_key="falso")
    return servidor.criar_app(cfg)


def test_fixture_tem_a_versao_fixada_no_dockerfile():
    assert re.search(r"@bitbonsai/mcpvault@([\w.-]+)", DOCKERFILE)[1] == PECAS["mcpvault"]["versao"]
    assert re.search(r"paperless-mcp==([\w.-]+)", DOCKERFILE)[1] == PECAS["paperless-mcp"]["versao"]


def test_bloqueadas_existem_nas_pecas():
    inexistentes = sorted(servidor.BLOQUEADAS - _nomes_reais())
    assert not inexistentes, f"Nomes em BLOQUEADAS que não existem nas peças: {inexistentes}"


def test_apagar_do_paperless_fica_bloqueado():
    # delete_share_link fica de fora: revogar link público reduz exposição (decisão do Leonardo).
    apagar = {f"paperless_{n}" for n in PECAS["paperless-mcp"]["so_com_enable_delete"]} - {"paperless_delete_share_link"}
    assert apagar <= servidor.BLOQUEADAS


async def test_bloqueadas_somem_do_app_montado(app):
    async with Client(app) as c:
        visiveis = {t.name for t in await c.list_tools()}
    assert not servidor.BLOQUEADAS & visiveis
    assert not PROIBIDAS & visiveis
    assert ESSENCIAIS <= visiveis
    assert _nomes_reais() - servidor.BLOQUEADAS <= visiveis


async def test_bloqueada_nao_pode_ser_chamada(app):
    async with Client(app) as c:
        assert (await c.call_tool("vault_read_note", {})).data == "ok"
        for nome in sorted(servidor.BLOQUEADAS):
            with pytest.raises(ToolError, match="Unknown tool"):
                await c.call_tool(nome, {})
