"""Busca por palavra nas notas do vault (SQLite FTS5 em memória). Sem FastMCP: serve também ao terminal.

    python -m assistente.vault_busca --vault <pasta> "texto" [--tipo X] [--status Y] [--pasta Z] [-n 5] [--json]

Só lê. O índice nasce na primeira busca e é refeito quando muda o conjunto (caminho, mtime_ns, tamanho)
dos arquivos `.md`. A consulta do usuário nunca vira sintaxe FTS: cada palavra entra entre aspas.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

IGNORADOS = {".git", ".obsidian", ".stversions", ".trash", "anexos", "templates"}
PADRAO_CONFLITO = re.compile(r"\.sync-conflict-")
# Notas que ficam fora do resultado da busca: o arquivo de perguntas da medida (2b.10) tem todas as palavras
# das perguntas e apareceria em 1º em buscas de verdade. Continuam legíveis por ler_nota.
FORA_DA_BUSCA = frozenset({"90-meta/perguntas-da-busca.md"})
# Pesos do bm25, na ordem das colunas indexadas: titulo, arquivo, tags, resumo, corpo. Ajuste no Passo 2.
PESOS = (10, 8, 5, 4, 1)
LIMITE_PADRAO = 5
LIMITE_MAXIMO = 20
TAMANHO_RESUMO = 300
TAMANHO_CONSULTA = 4096  # bytes, como o fts_query.rs do ai-memory
STOPWORDS = frozenset(
    "a o e de da do das dos em no na nos nas um uma que para por com como se ao à os as é eu meu minha "
    "sobre qual quais quando onde me mim pode posso devo cada porque quanto quantos fiz anotei".split())


@dataclass
class Nota:
    caminho: str  # relativo à raiz, com `/`
    titulo: str
    resumo: str
    tags: str
    tipo: str
    status: str
    corpo: str
    arquivo: str = field(default="")  # nome sem extensão, `-` e `_` viram espaço


# ---------------- leitura das notas ----------------

def _valor(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def separar_frontmatter(texto: str) -> tuple[dict[str, object], str]:
    """Subconjunto de YAML: `chave: valor`, `chave: [a, b]` e lista `- a`. Devolve (frontmatter, corpo)."""
    texto = texto.lstrip("﻿").replace("\r\n", "\n")
    if not texto.startswith("---\n"):
        return {}, texto
    fim = texto.find("\n---", 3)
    if fim == -1:
        return {}, texto
    bloco, resto = texto[4:fim], texto[fim + 4:]
    resto = resto.split("\n", 1)[1] if "\n" in resto else ""
    dados: dict[str, object] = {}
    chave = None
    for linha in bloco.split("\n"):
        if m := re.match(r"^\s+-\s+(.*)$", linha) or re.match(r"^-\s+(.*)$", linha):
            if chave is not None:
                lista = dados.setdefault(chave, [])
                if isinstance(lista, list):
                    lista.append(_valor(m[1]))
            continue
        m = re.match(r"^([^\s:#][^:]*):\s*(.*)$", linha)
        if not m:
            continue
        chave, v = m[1].strip(), m[2].strip()
        if v.startswith("[") and v.endswith("]"):
            dados[chave] = [_valor(i) for i in v[1:-1].split(",") if i.strip()]
        elif v == "":
            dados[chave] = []  # pode ser seguida de itens `- a`
        else:
            dados[chave] = _valor(v)
    return dados, resto


def _texto(v: object) -> str:
    if isinstance(v, list):
        return " ".join(str(i) for i in v)
    return str(v) if v is not None else ""


def _h1_e_resumo(corpo: str) -> tuple[str, str]:
    linhas = corpo.split("\n")
    for i, linha in enumerate(linhas):
        if linha.startswith("# "):
            h1 = linha[2:].strip()
            j = i + 1
            while j < len(linhas) and not linhas[j].strip():
                j += 1
            bloco = []
            while j < len(linhas) and linhas[j].startswith(">"):
                bloco.append(linhas[j].lstrip(">").strip())
                j += 1
            return h1, " ".join(p for p in bloco if p)[:TAMANHO_RESUMO]
    return "", ""


def ler_nota(raiz: Path, caminho: Path) -> Nota:
    texto = caminho.read_text(encoding="utf-8")
    fm, corpo = separar_frontmatter(texto)
    h1, resumo = _h1_e_resumo(corpo)
    rel = caminho.relative_to(raiz).as_posix()
    return Nota(
        caminho=rel, titulo=_texto(fm.get("titulo")).strip() or h1 or caminho.stem,
        resumo=resumo, tags=_texto(fm.get("tags")), tipo=_texto(fm.get("tipo")).strip(),
        status=_texto(fm.get("status")).strip(), corpo=corpo,
        arquivo=re.sub(r"[-_]+", " ", caminho.stem))


Assinatura = tuple[tuple[str, int, int], ...]


def listar_arquivos(raiz: Path) -> list[tuple[Path, int, int]]:
    """Os `.md` da raiz fora das pastas e dos arquivos ignorados. Link simbólico para fora da raiz: ignora."""
    real = Path(os.path.realpath(raiz))
    achados: list[tuple[Path, int, int]] = []

    def andar(pasta: Path) -> None:
        try:
            entradas = list(os.scandir(pasta))
        except OSError:
            log.warning("Não consegui listar %s", pasta)
            return
        for e in entradas:
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in IGNORADOS:
                        andar(Path(e.path))
                    continue
                if not e.name.endswith(".md") or PADRAO_CONFLITO.search(e.name):
                    continue
                if e.is_symlink():
                    alvo = Path(os.path.realpath(e.path))
                    if not alvo.is_relative_to(real) or not alvo.is_file():
                        continue
                st = e.stat()  # segue o link
                achados.append((Path(e.path), st.st_mtime_ns, st.st_size))
            except OSError:
                log.warning("Não consegui ler %s", e.path)

    andar(raiz)
    return sorted(achados)


# ---------------- consulta ----------------

def preparar_consulta(texto: str) -> str:
    """Texto livre → expressão FTS segura: palavras entre aspas, juntadas por OR. Vazio se não sobrar palavra."""
    texto = texto.encode("utf-8")[:TAMANHO_CONSULTA].decode("utf-8", errors="ignore").replace("\x00", " ")
    palavras = [p for p in texto.split() if any(c.isalnum() for c in p)]
    uteis = [p for p in palavras if p.lower() not in STOPWORDS]
    return " OR ".join('"' + p.replace('"', '""') + '"' for p in (uteis or palavras))


class IndiceVault:
    """Índice FTS5 em memória de uma pasta; refeito só quando o conjunto de arquivos muda."""

    def __init__(self, raiz: Path | str):
        self.raiz = Path(raiz)
        self._assinatura: Assinatura | None = None
        self._con: sqlite3.Connection | None = None
        self._trava = threading.Lock()
        self.reconstrucoes = 0

    def _construir(self, arquivos: list[tuple[Path, int, int]]) -> sqlite3.Connection:
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.execute('CREATE VIRTUAL TABLE t USING fts5(titulo, arquivo, tags, resumo, corpo, '
                    'caminho UNINDEXED, tipo UNINDEXED, status UNINDEXED, '
                    'tokenize="unicode61 remove_diacritics 2")')
        for caminho, _, _ in arquivos:
            try:
                n = ler_nota(self.raiz, caminho)
            except (OSError, UnicodeDecodeError) as e:
                log.warning("Nota pulada (%s): %s", type(e).__name__, caminho)
                continue
            con.execute("INSERT INTO t VALUES (?,?,?,?,?,?,?,?)",
                        (n.titulo, n.arquivo, n.tags, n.resumo, n.corpo, n.caminho, n.tipo, n.status))
        return con

    def _atual(self) -> sqlite3.Connection:
        arquivos = listar_arquivos(self.raiz)
        assinatura = tuple((a.relative_to(self.raiz).as_posix(), m, t) for a, m, t in arquivos)
        if self._con is None or assinatura != self._assinatura:
            if self._con is not None:
                self._con.close()
            self._con = self._construir(arquivos)
            self._assinatura = assinatura
            self.reconstrucoes += 1
        return self._con

    def buscar(self, texto: str, tipo: str | None = None, status: str | None = None,
               pasta: str | None = None, limite: int = LIMITE_PADRAO) -> list[dict]:
        consulta = preparar_consulta(texto or "")
        if not consulta:
            return []
        limite = max(1, min(int(limite), LIMITE_MAXIMO))
        sql = ["SELECT caminho, titulo, resumo, bm25(t, %s) AS r FROM t WHERE t MATCH ?" % ", ".join(map(str, PESOS))]
        args: list[object] = [consulta]
        sql.append("AND caminho NOT IN (%s)" % ", ".join("?" * len(FORA_DA_BUSCA)))
        args += sorted(FORA_DA_BUSCA)
        if tipo:
            sql.append("AND lower(tipo) = lower(?)")
            args.append(tipo.strip())
        if status:
            sql.append("AND lower(status) = lower(?)")
            args.append(status.strip())
        if pasta and (p := pasta.strip().strip("/")):
            sql.append("AND (caminho = ? OR substr(caminho, 1, ?) = ?)")
            args += [p, len(p) + 1, p + "/"]
        sql.append("ORDER BY r, caminho LIMIT ?")
        args.append(limite)
        with self._trava:
            con = self._atual()
            try:
                linhas = con.execute(" ".join(sql), args).fetchall()
            except sqlite3.OperationalError as e:
                log.warning("Consulta recusada pelo FTS: %s", e)
                return []
        return [{"caminho": c, "titulo": t, "resumo": r, "pontuacao": round(-b, 3)} for c, t, r, b in linhas]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assistente.vault_busca", description="Busca nas notas do vault.")
    ap.add_argument("texto")
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--tipo")
    ap.add_argument("--status")
    ap.add_argument("--pasta")
    ap.add_argument("-n", type=int, default=LIMITE_PADRAO)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.vault.is_dir():
        print(f"Pasta não existe: {a.vault}", file=sys.stderr)
        return 2
    achados = IndiceVault(a.vault).buscar(a.texto, a.tipo, a.status, a.pasta, a.n)
    if a.json:
        print(json.dumps(achados, ensure_ascii=False, indent=2))
    else:
        for r in achados:
            print(f"{r['caminho']} — {r['titulo']}")
            if r["resumo"]:
                print(f"    {r['resumo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
