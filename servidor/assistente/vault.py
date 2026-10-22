"""Ferramentas nossas sobre o vault (além do mcpvault): busca por relevância e, nos próximos passos, leitura com versão.

Só aqui entra lógica do vault; a busca em si fica em vault_busca.py (sem FastMCP).
"""

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import vault_busca
from .banco import caminho_da_nota
from .vault_busca import LIMITE_PADRAO, IndiceVault

LEITURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

# Nomes para o registro (registro.py) e para o teste de classificação. Os próximos passos acrescentam.
LEITURAS_VAULT = {"buscar_vault", "ler_nota", "notas_recentes"}
ESCRITAS_VAULT: set[str] = set()

LIMITE_CONTEUDO = 200_000  # caracteres devolvidos por ler_nota
LIMITE_RELACIONADAS = 10
RECENTES_PADRAO, RECENTES_MAXIMO = 10, 30
IGNORADOS_ESCRITA = {".git", ".obsidian", ".stversions", ".trash"}
FUSO = ZoneInfo("America/Sao_Paulo")
WIKILINK = re.compile(r"\[\[([^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")


def versao_de(conteudo: bytes) -> str:
    """Versão de uma nota: 16 primeiros hex do sha256 dos bytes do arquivo."""
    return hashlib.sha256(conteudo).hexdigest()[:16]


def caminho_seguro(raiz: Path, caminho: str) -> Path:
    """Caminho real de uma nota dentro do vault; ToolError se o formato é inválido ou se sai da raiz.

    Todo passo que lê ou escreve nota passa por aqui. Não exige que o arquivo exista.
    """
    limpo = caminho_da_nota(caminho)
    if limpo is None:
        raise ToolError("Caminho de nota vazio: use algo como 50-diario/2026/2026-10-20.md.")
    real_raiz = Path(os.path.realpath(raiz))
    real = Path(os.path.realpath(real_raiz / limpo))
    if not real.is_relative_to(real_raiz):
        raise ToolError("Caminho fora do vault")
    if real == real_raiz or set(real.relative_to(real_raiz).parts) & IGNORADOS_ESCRITA:
        raise ToolError("Caminho fora do vault")
    return real


@dataclass
class _Grafo:
    notas: dict[str, vault_busca.Nota] = field(default_factory=dict)
    atualizado: dict[str, str] = field(default_factory=dict)  # caminho -> 'AAAA-MM-DD HH:MM' (frontmatter ou mtime)
    mtime: dict[str, int] = field(default_factory=dict)
    links: dict[str, list[str]] = field(default_factory=dict)  # caminho -> destinos resolvidos, na ordem
    backlinks: dict[str, list[str]] = field(default_factory=dict)


def _formato_data(texto: str) -> str | None:
    texto = texto.strip()
    for formato in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(texto, formato)
        except ValueError:
            continue
        return d.strftime("%Y-%m-%d %H:%M")
    return None


def _resolver(alvo: str, por_nome: dict[str, list[str]], caminhos: set[str]) -> str | None:
    alvo = alvo.strip().removesuffix(".md")
    if not alvo:
        return None
    if "/" in alvo:
        if alvo + ".md" in caminhos:
            return alvo + ".md"
        alvo = alvo.rsplit("/", 1)[1]
    achados = por_nome.get(alvo) or por_nome.get(alvo.casefold())
    return achados[0] if achados else None


def links_do_texto(texto: str) -> list[str]:
    """Alvos crus dos wikilinks do texto, na ordem, sem repetir."""
    vistos: dict[str, None] = {}
    for m in WIKILINK.finditer(texto):
        vistos.setdefault(m[1].strip(), None)
    return list(vistos)


class GrafoVault:
    """Notas, links e backlinks lidos uma vez; refeito quando muda o conjunto (caminho, mtime, tamanho)."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self._assinatura = None
        self._grafo = _Grafo()
        self._trava = threading.Lock()
        self._por_nome: dict[str, list[str]] = {}

    def atual(self) -> _Grafo:
        with self._trava:
            arquivos = vault_busca.listar_arquivos(self.raiz)
            assinatura = tuple((a.relative_to(self.raiz).as_posix(), m, t) for a, m, t in arquivos)
            if assinatura != self._assinatura:
                self._grafo = self._construir(arquivos)
                self._assinatura = assinatura
            return self._grafo

    def _construir(self, arquivos) -> _Grafo:
        g = _Grafo()
        for caminho, mtime, _ in arquivos:
            try:
                nota = vault_busca.ler_nota(self.raiz, caminho)
                fm, _corpo = vault_busca.separar_frontmatter(caminho.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            g.notas[nota.caminho] = nota
            g.mtime[nota.caminho] = mtime
            data = _formato_data(vault_busca._texto(fm.get("atualizado")))
            g.atualizado[nota.caminho] = data or datetime.fromtimestamp(mtime / 1e9, FUSO).strftime("%Y-%m-%d %H:%M")
        por_nome: dict[str, list[str]] = {}
        for c in sorted(g.notas):
            nome = c.rsplit("/", 1)[-1].removesuffix(".md")
            por_nome.setdefault(nome, []).append(c)
            por_nome.setdefault(nome.casefold(), []).append(c)
        caminhos = set(g.notas)
        for c, nota in g.notas.items():
            destinos: list[str] = []
            for alvo in links_do_texto(nota.corpo):
                d = _resolver(alvo, por_nome, caminhos)
                if d and d != c and d not in destinos:
                    destinos.append(d)
            g.links[c] = destinos
            for d in destinos:
                g.backlinks.setdefault(d, []).append(c)
        for lista in g.backlinks.values():
            lista.sort()
        self._por_nome = por_nome
        return g

    def destinos_de(self, texto: str, proprio: str) -> list[str]:
        """Links de um texto avulso (nota que não está no grafo), resolvidos."""
        g = self.atual()
        caminhos = set(g.notas)
        saida: list[str] = []
        for alvo in links_do_texto(texto):
            d = _resolver(alvo, self._por_nome, caminhos)
            if d and d != proprio and d not in saida:
                saida.append(d)
        return saida


def criar_servidor_vault(raiz: Path) -> FastMCP:
    mcp = FastMCP("vault-busca")
    indice = IndiceVault(raiz)
    grafo = GrafoVault(raiz)

    @mcp.tool(annotations=LEITURA)
    def buscar_vault(
        texto: Annotated[str, Field(description="Palavras a procurar, em linguagem natural. Acento não importa.")],
        tipo: Annotated[str | None, Field(description="Só notas com este tipo no frontmatter (ex.: projeto, decisao).")] = None,
        status: Annotated[str | None, Field(description="Só notas com este status (ex.: ativo, arquivado).")] = None,
        pasta: Annotated[str | None, Field(description="Só notas dentro desta pasta do vault (ex.: 10-projetos).")] = None,
    ) -> list[dict]:
        """Primeiro passo para achar uma nota. Devolve caminho, título e resumo das 5 mais relevantes, sem o corpo."""
        return indice.buscar(texto, tipo, status, pasta, LIMITE_PADRAO)

    @mcp.tool(annotations=LEITURA)
    def ler_nota(
        caminho: Annotated[str, Field(description="Caminho da nota relativo ao vault (ex.: 20-areas/perfil-do-leonardo.md).")],
        relacionadas: Annotated[bool, Field(description="Se verdadeiro, traz também as notas ligadas (até 10).")] = True,
    ) -> dict:
        """Lê uma nota do vault inteira, com a versao (use em escrever_nota) e as notas ligadas a ela (links e backlinks), só com o resumo."""
        real = caminho_seguro(raiz, caminho)
        if not real.is_file():
            raise ToolError(f"Nota não existe: {caminho}")
        try:
            dados = real.read_bytes()
        except OSError:
            raise ToolError(f"Nota não existe: {caminho}") from None
        texto = dados.decode("utf-8", errors="replace")
        saida: dict = {"caminho": caminho_da_nota(caminho), "conteudo": texto, "versao": versao_de(dados)}
        if len(texto) > LIMITE_CONTEUDO:
            saida["conteudo"] = texto[:LIMITE_CONTEUDO]
            saida["cortado"] = True
        if relacionadas:
            g = grafo.atual()
            rel = real.relative_to(Path(os.path.realpath(raiz))).as_posix()
            if rel in g.links:
                links = g.links[rel]
            else:
                links = grafo.destinos_de(texto, rel)
            itens = [(c, "link") for c in links]
            itens += [(c, "backlink") for c in g.backlinks.get(rel, []) if c not in links]
            saida["relacionadas"] = [
                {"caminho": c, "titulo": g.notas[c].titulo, "resumo": g.notas[c].resumo, "relacao": r}
                for c, r in itens[:LIMITE_RELACIONADAS]]
        else:
            saida["relacionadas"] = []
        return saida

    @mcp.tool(annotations=LEITURA)
    def notas_recentes(
        n: Annotated[int, Field(description="Quantas notas (1 a 30).")] = RECENTES_PADRAO,
        pasta: Annotated[str | None, Field(description="Só notas dentro desta pasta do vault (ex.: 10-projetos).")] = None,
    ) -> list[dict]:
        """Lista as notas mudadas por último, pelo campo atualizado do frontmatter (sem ele, pela data do arquivo)."""
        n = max(1, min(int(n), RECENTES_MAXIMO))
        g = grafo.atual()
        caminhos = list(g.notas)
        if pasta and (p := pasta.strip().strip("/")):
            caminhos = [c for c in caminhos if c == p or c.startswith(p + "/")]
        caminhos.sort(key=lambda c: (g.atualizado[c], g.mtime[c], c), reverse=True)
        return [{"caminho": c, "titulo": g.notas[c].titulo, "atualizado": g.atualizado[c]} for c in caminhos[:n]]

    return mcp
