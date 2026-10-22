"""Importação dos resumos de sessão do Claude Code para a tabela `sessoes` (Sprint 2b, Passo 11; ficha 5, regra 9).

    python -m assistente.sessoes importar < resumos.jsonl

Lê JSONL da entrada padrão: um resumo por linha (o JSON que `ferramentas/sessoes/fila.py` grava), no máximo
2.000 linhas e 2 MB por execução; o que passa disso fica para a próxima (a linha do corte sai em `recusadas`).
Cada resumo é dado de fora: tipos conferidos um a um, textos cortados ao tamanho das colunas, listas cortadas
(arquivos 50, comandos 30, commits 20), campo desconhecido descartado. Linha inválida é recusada sozinha; as
outras seguem.

Grava pela conexão de escrita (`DATABASE_URL_ESCRITA`, só INSERT e SELECT em `sessoes`) numa transação, com UMA
linha de `auditoria` por execução (`sessoes_importar`, `sessoes`, `criar`; `dados` só com as contagens e as
máquinas). O mesmo (`sessao`, `fim`) já gravado, ou repetido na entrada, conta como repetido e não entra.

Imprime em JSON: {"aceitas": [ids], "repetidas": [ids], "recusadas": [{"linha": n, "motivo": "..."}]}.
As aceitas e as repetidas já estão no banco: o envio pode marcá-las como enviadas.
Código 0 se rodou (mesmo com recusadas); 2 se o banco falhou ou falta a variável (sem a URL na mensagem).
Duas importações ao mesmo tempo com o mesmo resumo: a segunda esbarra no índice único e sai com 2 sem gravar
nada; a próxima execução conta o resumo como repetido.

Segredos (Passo 5): o resumo já sai da máquina sem segredo, mas é dado de fora. Antes de gravar, `titulo`,
`comandos`, `arquivos` e a mensagem dos `commits` passam por `segredos.tirar_segredos` (cada achado vira
`[segredo:<tipo>]`). Aqui redigir é certo: o texto não é do dono, e recusar perderia a sessão inteira.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, BinaryIO

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .db import opcoes_engine
from .modelos import Auditoria, Sessao
from .segredos import tirar_segredos

MAX_LINHAS = 2000
MAX_BYTES = 2 * 1024 * 1024
VERSOES_CONHECIDAS = {2}  # VERSAO_RESUMO de ferramentas/sessoes/resumo.py
ID_SESSAO = re.compile(r"[A-Za-z0-9-]{8,80}")  # sempre com fullmatch
ID_COMMIT = re.compile(r"[0-9a-f]{7,40}")
# Tamanho de cada coluna de texto (modelos.Sessao) e dos itens das listas.
TAMANHOS = {"projeto": 120, "raiz": 300, "maquina": 60, "titulo": 200, "motivo_fim": 40}
LISTAS = {"arquivos": (50, 300), "comandos": (30, 300)}  # (itens, caracteres por item)
MAX_COMMITS, MAX_MENSAGEM_COMMIT = 20, 200
MAX_DURACAO_MIN = 1_000_000
ANOS = (2000, 2100)
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


class Recusa(ValueError):
    """Resumo inválido; a mensagem diz o campo e o problema, nunca o valor."""


REDIGIDOS = {"titulo", "comandos", "arquivos", "commits.mensagem"}  # passam por tirar_segredos antes do corte


def _texto(valor: Any, campo: str, tamanho: int, vazio: bool = True) -> str:
    if not isinstance(valor, str):
        raise Recusa(f"{campo}: não é texto")
    if campo in REDIGIDOS:
        # Antes do corte: um segredo cortado ao meio deixaria de casar com o padrão e entraria pela metade.
        valor = tirar_segredos(valor)
    # Surrogate solto (vindo de "\ud83d") vira "?"; caractere de controle (inclusive NUL, que o Postgres recusa)
    # vira espaço.
    limpo = _CONTROLE.sub(" ", valor.encode("utf-8", "replace").decode("utf-8"))[:tamanho]
    if not vazio and not limpo.strip():
        raise Recusa(f"{campo}: vazio")
    return limpo


def _data(valor: Any, campo: str, nula: bool = False) -> datetime | None:
    if valor is None and nula:
        return None
    if not isinstance(valor, str) or len(valor) > 40:
        raise Recusa(f"{campo}: não é data ISO")
    try:
        momento = datetime.fromisoformat(valor)
    except ValueError:
        raise Recusa(f"{campo}: não é data ISO") from None
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise Recusa(f"{campo}: data sem fuso")
    if not ANOS[0] <= momento.year <= ANOS[1]:
        raise Recusa(f"{campo}: ano fora de {ANOS[0]}–{ANOS[1]}")
    # UTC sempre: o SQLite (testes) grava sem fuso, e o índice único compara o texto.
    return momento.astimezone(timezone.utc)


def _inteiro(valor: Any, campo: str, minimo: int, maximo: int) -> int:
    if type(valor) is not int or not minimo <= valor <= maximo:  # bool não passa
        raise Recusa(f"{campo}: não é inteiro entre {minimo} e {maximo}")
    return valor


def _booleano(valor: Any, campo: str) -> bool:
    if type(valor) is not bool:
        raise Recusa(f"{campo}: não é true ou false")
    return valor


def _lista(valor: Any, campo: str) -> list:
    if not isinstance(valor, list):
        raise Recusa(f"{campo}: não é lista")
    return valor


def _commits(valor: Any) -> list[dict]:
    commits = []
    for item in _lista(valor, "commits")[:MAX_COMMITS]:
        if not isinstance(item, dict):
            raise Recusa("commits: item não é objeto")
        cid = item.get("id")
        if not isinstance(cid, str) or ID_COMMIT.fullmatch(cid) is None:
            raise Recusa("commits: id inválido")
        commits.append({"id": cid, "mensagem": _texto(item.get("mensagem"), "commits.mensagem", MAX_MENSAGEM_COMMIT)})
    return commits


def validar(dado: Any) -> dict:
    """Resumo validado e limpo, pronto para `Sessao(**...)`. Campo desconhecido é descartado. Levanta `Recusa`."""
    if not isinstance(dado, dict):
        raise Recusa("não é um objeto JSON")
    faltando = sorted({"sessao", "projeto", "raiz", "maquina", "inicio", "fim", "duracao_min", "titulo", "arquivos",
                       "comandos", "commits", "passagem", "motivo_fim", "versao_resumo"} - dado.keys())
    if faltando:
        raise Recusa(f"faltam campos: {', '.join(faltando)}")
    sessao = dado["sessao"]
    if not isinstance(sessao, str) or ID_SESSAO.fullmatch(sessao) is None:
        raise Recusa("sessao: id inválido (8 a 80 de [A-Za-z0-9-])")
    if type(dado["versao_resumo"]) is not int or dado["versao_resumo"] not in VERSOES_CONHECIDAS:
        raise Recusa(f"versao_resumo: desconhecida (conhecidas: {sorted(VERSOES_CONHECIDAS)})")
    inicio, fim = _data(dado["inicio"], "inicio", nula=True), _data(dado["fim"], "fim")
    if inicio is not None and inicio > fim:
        raise Recusa("inicio: depois do fim")
    limpo = {
        "sessao": sessao,
        **{campo: _texto(dado[campo], campo, tamanho, vazio=campo in ("titulo", "motivo_fim"))
           for campo, tamanho in TAMANHOS.items()},
        "inicio": inicio,
        "fim": fim,
        "duracao_min": _inteiro(dado["duracao_min"], "duracao_min", 0, MAX_DURACAO_MIN),
        "commits": _commits(dado["commits"]),
        "passagem": _booleano(dado["passagem"], "passagem"),
        "parcial": _booleano(dado.get("parcial", False), "parcial"),
        "versao_resumo": dado["versao_resumo"],
    }
    for campo, (itens, tamanho) in LISTAS.items():
        limpo[campo] = [_texto(item, campo, tamanho) for item in _lista(dado[campo], campo)[:itens]]
    return limpo


def ler_entrada(fluxo: BinaryIO) -> tuple[list[tuple[int, bytes]], list[dict]]:
    """(linhas não vazias com o número, recusas de limite). Lê no máximo MAX_BYTES; o resto fica para depois."""
    dados = fluxo.read(MAX_BYTES + 1)
    cortou = len(dados) > MAX_BYTES
    linhas = dados[:MAX_BYTES].split(b"\n")
    if cortou:
        linhas = linhas[:-1]  # a última linha veio pela metade
    resumos, recusas = [], []
    for numero, linha in enumerate(linhas, start=1):
        if not linha.strip():
            continue
        if len(resumos) == MAX_LINHAS:
            recusas.append({"linha": numero, "motivo": f"passou de {MAX_LINHAS} linhas por execução; esta e as "
                                                      "seguintes ficam para a próxima"})
            return resumos, recusas
        resumos.append((numero, linha))
    if cortou:
        recusas.append({"linha": len(linhas) + 1, "motivo": f"passou de {MAX_BYTES // (1024 * 1024)} MB por execução; "
                                                            "esta e as seguintes ficam para a próxima"})
    return resumos, recusas


def _utc(momento: datetime) -> datetime:
    # O SQLite (testes) devolve sem fuso o que gravou em UTC; o Postgres devolve com fuso.
    return (momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def importar(fluxo: BinaryIO, engine: Engine) -> dict:
    """Valida e grava os resumos da entrada. Devolve aceitas, repetidas e recusadas. Erro de banco sobe."""
    linhas, recusadas = ler_entrada(fluxo)
    validos: list[tuple[int, dict]] = []
    for numero, linha in linhas:
        try:
            try:
                dado = json.loads(linha.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                raise Recusa("não é JSON válido em UTF-8") from None
            validos.append((numero, validar(dado)))
        except Recusa as e:
            recusadas.append({"linha": numero, "motivo": str(e)})
    recusadas.sort(key=lambda r: r["linha"])

    aceitas: list[dict] = []
    repetidas: list[str] = []
    with Session(engine) as s, s.begin():
        ids = sorted({r["sessao"] for _, r in validos})
        vistos = {(sessao, _utc(fim)) for sessao, fim in s.execute(
            select(Sessao.sessao, Sessao.fim).where(Sessao.sessao.in_(ids)))} if ids else set()
        for _, resumo in validos:
            chave = (resumo["sessao"], resumo["fim"])
            if chave in vistos:
                repetidas.append(resumo["sessao"])
                continue
            vistos.add(chave)
            aceitas.append(resumo)
            s.add(Sessao(**resumo))
        maquinas = sorted({r["maquina"] for _, r in validos})
        s.add(Auditoria(ferramenta="sessoes_importar", tabela="sessoes", registro_id=None, acao="criar",
                        dados={"quantidade": len(aceitas), "repetidas": len(repetidas), "recusadas": len(recusadas),
                               "maquinas": maquinas}))
    return {"aceitas": [r["sessao"] for r in aceitas], "repetidas": repetidas, "recusadas": recusadas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistente.sessoes",
                                     description="Sessões do Claude Code (ficha 5, regra 9).")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("importar", help="Lê resumos em JSONL da entrada padrão e grava na tabela sessoes.")
    parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL_ESCRITA", "")
    if not url:
        print("sessoes: DATABASE_URL_ESCRITA não definida.", file=sys.stderr)
        return 2
    engine = create_engine(url, **opcoes_engine(url))
    try:
        resultado = importar(sys.stdin.buffer, engine)
    except Exception as e:  # noqa: BLE001 (qualquer falha do banco vira código 2, sem a URL com senha)
        print(f"sessoes: não consegui gravar ({type(e).__name__}); nada foi importado.", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(json.dumps(resultado, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
