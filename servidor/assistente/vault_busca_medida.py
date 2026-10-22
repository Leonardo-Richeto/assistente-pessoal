"""Mede a busca do vault (item 2b.10): quantas vezes a nota esperada vem entre as 5 primeiras.

    python -m assistente.vault_busca_medida --vault <pasta> [--perguntas <arquivo>] [--pesos 10,8,5,4,1] [--json]

O arquivo de perguntas é markdown com uma tabela `| pergunta | nota esperada |`; a nota esperada é um caminho
relativo ao vault (mais de um, separados por ` ou `). Padrão: `<vault>/90-meta/perguntas-da-busca.md`.
Só lê. `--pesos` troca `vault_busca.PESOS` só nesta execução, para comparar variações.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from assistente import vault_busca
from assistente.vault_busca import IndiceVault

LIMITE = 5


def ler_perguntas(arquivo: Path) -> list[tuple[str, list[str]]]:
    """Linhas `| pergunta | nota esperada |` da tabela; ignora cabeçalho, separador e outras linhas."""
    achadas: list[tuple[str, list[str]]] = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha.startswith("|"):
            continue
        colunas = [c.strip() for c in linha.strip("|").split("|")]
        if len(colunas) < 2 or not colunas[0] or not colunas[1]:
            continue
        if set(colunas[0]) <= set("-: ") or colunas[0].lower() == "pergunta":
            continue
        esperadas = [e.strip().strip("`") for e in colunas[1].split(" ou ") if e.strip()]
        achadas.append((colunas[0], esperadas))
    return achadas


def medir(vault: Path, perguntas: list[tuple[str, list[str]]], pesos: tuple[int, ...] | None = None,
          arquivo_perguntas: str | None = None) -> dict:
    """Roda cada pergunta e devolve o resultado por pergunta e os totais.

    `arquivo_perguntas` (caminho relativo ao vault) sai dos resultados: ele contém todas as palavras das
    perguntas e se acharia a si mesmo, o que não diz nada sobre a busca."""
    original = vault_busca.PESOS
    if pesos is not None:
        vault_busca.PESOS = pesos
    try:
        indice = IndiceVault(vault)
        indice.buscar("aquecimento")  # constrói o índice fora da medida de tempo
        itens = []
        tempo = 0.0
        for pergunta, esperadas in perguntas:
            cadastro = [e for e in esperadas if not (vault / e).is_file()]
            t0 = time.perf_counter()
            achadas = [r["caminho"] for r in indice.buscar(pergunta, limite=LIMITE + 1)
                       if r["caminho"] != arquivo_perguntas][:LIMITE]
            tempo += time.perf_counter() - t0
            posicoes = [achadas.index(e) + 1 for e in esperadas if e in achadas]
            itens.append({"pergunta": pergunta, "esperadas": esperadas, "achadas": achadas,
                          "posicao": min(posicoes) if posicoes else None, "erro_de_cadastro": cadastro})
    finally:
        vault_busca.PESOS = original
    validas = [i for i in itens if not (i["erro_de_cadastro"] and len(i["erro_de_cadastro"]) == len(i["esperadas"]))]
    n = len(validas)
    dentro = sum(1 for i in validas if i["posicao"])
    primeiro = sum(1 for i in validas if i["posicao"] == 1)
    mrr = sum(1 / i["posicao"] for i in validas if i["posicao"]) / n if n else 0.0
    return {"pesos": list(pesos or vault_busca.PESOS), "n": n, "acerto_entre_5": dentro, "acerto_em_1": primeiro,
            "mrr": round(mrr, 3), "ms_por_busca": round(tempo / len(itens) * 1000, 2) if itens else 0.0,
            "erros_de_cadastro": sum(1 for i in itens if i["erro_de_cadastro"]), "itens": itens}


def formatar(r: dict) -> str:
    linhas = []
    for i in r["itens"]:
        for e in i["erro_de_cadastro"]:
            linhas.append(f"AVISO erro de cadastro: nota esperada não existe: {e} (pergunta: {i['pergunta']})")
        pos = i["posicao"] if i["posicao"] else "fora"
        linhas.append(f"[{pos}] {i['pergunta']}")
        if not i["posicao"]:
            linhas.append(f"    esperada: {' ou '.join(i['esperadas'])}")
            linhas += [f"    {k}. {c}" for k, c in enumerate(i["achadas"], 1)] or ["    (nenhuma achada)"]
    n = r["n"]
    pct = f"{100 * r['acerto_entre_5'] / n:.0f}" if n else "0"
    linhas += ["", f"Pesos: {','.join(map(str, r['pesos']))}",
               f"Acerto entre as 5: {r['acerto_entre_5']}/{n} ({pct}%)",
               f"Acerto em 1º: {r['acerto_em_1']}/{n}", f"MRR: {r['mrr']:.3f}",
               f"Tempo médio por busca: {r['ms_por_busca']} ms"]
    if r["erros_de_cadastro"]:
        linhas.append(f"Erros de cadastro (fora da conta): {r['erros_de_cadastro']}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assistente.vault_busca_medida", description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--perguntas", type=Path)
    ap.add_argument("--pesos", help="cinco inteiros: título,arquivo,tags,resumo,corpo")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.vault.is_dir():
        print(f"Pasta não existe: {a.vault}", file=sys.stderr)
        return 2
    arquivo = a.perguntas or a.vault / "90-meta" / "perguntas-da-busca.md"
    if not arquivo.is_file():
        print(f"Arquivo de perguntas não existe: {arquivo}", file=sys.stderr)
        return 2
    pesos = None
    if a.pesos:
        try:
            pesos = tuple(int(p) for p in a.pesos.split(","))
        except ValueError:
            pesos = ()
        if len(pesos) != 5:
            print("--pesos pede 5 inteiros separados por vírgula", file=sys.stderr)
            return 2
    perguntas = ler_perguntas(arquivo)
    if not perguntas:
        print("Nenhuma pergunta na tabela", file=sys.stderr)
        return 2
    try:
        relativo = arquivo.resolve().relative_to(a.vault.resolve()).as_posix()
    except ValueError:
        relativo = None
    r = medir(a.vault, perguntas, pesos, relativo)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else formatar(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
