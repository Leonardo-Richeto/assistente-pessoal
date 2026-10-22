"""Envia os resumos pendentes da fila local para a tabela `sessoes` do i7 (Sprint 2b, Passo 11; ficha 5, regra 9).

    ASSISTENTE_SSH=usuario@i7 /usr/bin/python3 ferramentas/sessoes/enviar.py
    /usr/bin/python3 ferramentas/sessoes/enviar.py --comando "..."   # outro comando (testes)

Junta as pendentes de todas as subpastas de `pendentes/` (até 500 por vez e 2 MB, as mais antigas primeiro), manda
como JSONL para o importador do i7 pela Tailscale (SSH) e move para `enviadas/` as que o importador aceitou ou já
tinha (`aceitas` + `repetidas`), com `fila.marcar_enviada`. As recusadas ficam em `pendentes/`. Nada é apagado.
Comando que falha, demora mais de 120 s ou responde algo que não é o JSON esperado: nada se move.
O arquivo que mudou durante o envio (sessão retomada que terminou nesse meio-tempo) também fica: vai na próxima.

Não roda no fim da sessão (o SessionEnd tem 1,5 s): rode à mão ou por timer (launchd no Mac; ver README).
Log em `hooks.log` da pasta de estado (`fila.log`). Código 0 se enviou ou não havia o que enviar; 1 se faltou
configuração ou o envio falhou.

Só biblioteca padrão; compatível com Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fila  # noqa: E402

MAX_POR_VEZ = 500
MAX_BYTES = 2 * 1024 * 1024  # = o limite do importador por execução
TIMEOUT_S = 120
PASTA_APP_I7 = "/srv/assistente/app"
COMANDO_REMOTO = (
    "docker compose --project-directory %s exec -T servidor python -m assistente.sessoes importar" % PASTA_APP_I7
)
SEM_SSH = "Defina ASSISTENTE_SSH (ex.: usuario@i7). O PC do trabalho fica só com a fila local."
DESTINO_VALIDO = re.compile(r"[A-Za-z0-9._@-]{1,200}")  # usuario@maquina; nunca começa com "-" (opção do ssh)


class Pendente:
    """Um arquivo de `pendentes/` lido para o envio, com a marca do arquivo na hora da leitura."""

    def __init__(self, caminho: str, sessao: str, linha: bytes, marca: Tuple[int, int]) -> None:
        self.caminho = caminho
        self.sessao = sessao
        self.linha = linha
        self.marca = marca


def _marca(caminho: str) -> Optional[Tuple[int, int]]:
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def arquivos_pendentes() -> List[str]:
    """Todos os `<sessao>.json` de `pendentes/` (formato antigo e subpastas), os mais antigos primeiro."""
    base = os.path.join(fila.pasta_estado(), "pendentes")
    caminhos = []
    try:
        nomes = os.listdir(base)
    except OSError:
        return []
    for nome in nomes:
        caminho = os.path.join(base, nome)
        if os.path.isdir(caminho):
            try:
                caminhos.extend(os.path.join(caminho, n) for n in os.listdir(caminho))
            except OSError:
                continue
        else:
            caminhos.append(caminho)
    candidatos = []
    for caminho in caminhos:
        nome = os.path.basename(caminho)
        if not nome.endswith(".json") or nome.startswith(".") or not os.path.isfile(caminho):
            continue
        marca = _marca(caminho)
        if marca is not None:
            candidatos.append((marca[0], caminho))
    candidatos.sort()
    return [c for _, c in candidatos]


def ler_lote() -> Tuple[List[Pendente], int]:
    """(lote a enviar, quantas pendentes ficaram de fora pelo limite). Arquivo ruim fica e vai para o log."""
    lote: List[Pendente] = []
    total = 0
    caminhos = arquivos_pendentes()
    for indice, caminho in enumerate(caminhos):
        if len(lote) >= MAX_POR_VEZ:
            return lote, len(caminhos) - indice
        marca = _marca(caminho)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dado = json.load(f)
        except (OSError, ValueError) as e:
            fila.log("enviar: não li %s (%s); fica em pendentes" % (os.path.basename(caminho), type(e).__name__))
            continue
        sessao = dado.get("sessao") if isinstance(dado, dict) else None
        if marca is None or not fila.id_valido(sessao) or os.path.basename(caminho) != sessao + ".json":
            fila.log("enviar: %s não é um resumo válido; fica em pendentes" % os.path.basename(caminho))
            continue
        # ASCII: o surrogate solto e o acento atravessam o SSH sem depender da codificação do terminal.
        linha = json.dumps(dado, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        if len(linha) > MAX_BYTES:
            fila.log("enviar: %s passa de 2 MB; fica em pendentes" % os.path.basename(caminho))
            continue
        if total + len(linha) > MAX_BYTES:
            return lote, len(caminhos) - indice
        total += len(linha)
        lote.append(Pendente(caminho, sessao, linha, marca))
    return lote, 0


def comando_padrao() -> Optional[List[str]]:
    destino = os.environ.get("ASSISTENTE_SSH", "").strip()
    if not destino:
        return None
    if DESTINO_VALIDO.fullmatch(destino) is None or destino.startswith("-"):
        raise ValueError("ASSISTENTE_SSH inválida: use usuario@maquina")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", destino, COMANDO_REMOTO]


def _resposta(saida: bytes) -> Optional[Dict[str, Any]]:
    """O JSON do importador (a última linha não vazia da saída), ou None se não for o esperado."""
    linhas = [l for l in saida.decode("utf-8", "replace").splitlines() if l.strip()]
    if not linhas:
        return None
    try:
        dado = json.loads(linhas[-1])
    except ValueError:
        return None
    if not isinstance(dado, dict) or not all(isinstance(dado.get(k), list) for k in ("aceitas", "repetidas", "recusadas")):
        return None
    return dado


def _curto(texto: bytes) -> str:
    return " ".join(texto.decode("utf-8", "replace").split())[-300:]


def enviar(comando: List[str]) -> int:
    lote, de_fora = ler_lote()
    if not lote:
        print("Nada a enviar.")
        return 0
    try:
        r = subprocess.run(comando, input=b"".join(p.linha for p in lote), capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        fila.log("enviar: o comando passou de %d s; nada foi marcado como enviado" % TIMEOUT_S)
        print("Falhou: o envio passou de %d s. Nada mudou na fila." % TIMEOUT_S, file=sys.stderr)
        return 1
    except OSError as e:
        fila.log("enviar: não consegui rodar o comando (%s)" % type(e).__name__)
        print("Falhou: não consegui rodar o comando (%s). Nada mudou na fila." % type(e).__name__, file=sys.stderr)
        return 1
    resposta = _resposta(r.stdout) if r.returncode == 0 else None
    if resposta is None:
        fila.log("enviar: o comando saiu com %d; nada foi marcado como enviado: %s" % (r.returncode, _curto(r.stderr)))
        print("Falhou: o comando saiu com %d. Nada mudou na fila. %s" % (r.returncode, _curto(r.stderr)),
              file=sys.stderr)
        return 1

    no_banco = {s for s in resposta["aceitas"] + resposta["repetidas"] if isinstance(s, str)}
    movidas, mudaram = 0, 0
    for pendente in lote:
        if pendente.sessao not in no_banco:
            continue
        no_banco.discard(pendente.sessao)  # a mesma sessão em duas subpastas: marcar_enviada move as duas
        if _marca(pendente.caminho) != pendente.marca:
            mudaram += 1
            fila.log("enviar: %s mudou durante o envio; fica em pendentes" % pendente.sessao)
            continue
        try:
            fila.marcar_enviada(pendente.sessao)
            movidas += 1
        except (OSError, ValueError) as e:
            fila.log("enviar: não movi %s para enviadas (%s)" % (pendente.sessao, type(e).__name__))
    recusadas = [r for r in resposta["recusadas"] if isinstance(r, dict)]
    linhas = {indice + 1: p.sessao for indice, p in enumerate(lote)}
    for recusa in recusadas:
        fila.log("enviar: recusada %s: %s" % (linhas.get(recusa.get("linha"), "linha %s" % recusa.get("linha")),
                                              str(recusa.get("motivo"))[:200]))
    resumo = "enviadas %d de %d (aceitas %d, repetidas %d), recusadas %d, mudaram no envio %d, ficaram para depois %d" % (
        movidas, len(lote), len(resposta["aceitas"]), len(resposta["repetidas"]), len(recusadas), mudaram, de_fora)
    fila.log("enviar: " + resumo)
    print(resumo[:1].upper() + resumo[1:] + ".")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Envia as sessões pendentes para o banco do i7.")
    parser.add_argument("--comando", help="Comando que recebe o JSONL na entrada (padrão: ssh para ASSISTENTE_SSH).")
    args = parser.parse_args(argv)
    if args.comando:
        comando = shlex.split(args.comando)
    else:
        try:
            comando = comando_padrao()
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        if comando is None:
            print(SEM_SSH, file=sys.stderr)
            return 1
    return enviar(comando)


if __name__ == "__main__":
    sys.exit(main())
