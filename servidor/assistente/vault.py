"""Ferramentas nossas sobre o vault (além do mcpvault): busca por relevância e, nos próximos passos, leitura com versão.

Só aqui entra lógica do vault; a busca em si fica em vault_busca.py (sem FastMCP).
"""

from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .vault_busca import LIMITE_PADRAO, IndiceVault

LEITURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

# Nomes para o registro (registro.py) e para o teste de classificação. Os próximos passos acrescentam.
LEITURAS_VAULT = {"buscar_vault"}
ESCRITAS_VAULT: set[str] = set()


def criar_servidor_vault(raiz: Path) -> FastMCP:
    mcp = FastMCP("vault-busca")
    indice = IndiceVault(raiz)

    @mcp.tool(annotations=LEITURA)
    def buscar_vault(
        texto: Annotated[str, Field(description="Palavras a procurar, em linguagem natural. Acento não importa.")],
        tipo: Annotated[str | None, Field(description="Só notas com este tipo no frontmatter (ex.: projeto, decisao).")] = None,
        status: Annotated[str | None, Field(description="Só notas com este status (ex.: ativo, arquivado).")] = None,
        pasta: Annotated[str | None, Field(description="Só notas dentro desta pasta do vault (ex.: 10-projetos).")] = None,
    ) -> list[dict]:
        """Primeiro passo para achar uma nota. Devolve caminho, título e resumo das 5 mais relevantes, sem o corpo."""
        return indice.buscar(texto, tipo, status, pasta, LIMITE_PADRAO)

    return mcp
