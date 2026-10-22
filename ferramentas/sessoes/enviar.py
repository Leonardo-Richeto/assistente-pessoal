"""Envia os resumos pendentes da fila local para a tabela `sessoes` do i7 (Sprint 2b, Passo 11; ficha 5, regra 9).

    ASSISTENTE_SSH=usuario@i7 /usr/bin/python3 ferramentas/sessoes/enviar.py
    /usr/bin/python3 ferramentas/sessoes/enviar.py --comando "..."   # outro comando (testes)

Junta as pendentes de todas as subpastas de `pendentes/` (até 500 por vez e 2 MB, as mais antigas primeiro), manda
como JSONL para o importador do i7 pela Tailscale (SSH) e move, arquivo por arquivo (o caminho exato do lote):
- para `enviadas/<projeto>/<sessao>.<fim>.json` as que o importador aceitou ou já tinha (`aceitas` + `repetidas`);
- para `recusadas/<projeto>/<sessao>.<fim>.json` as recusadas, com o motivo em `<sessao>.<fim>.motivo.txt` ao lado.
  Assim a recusada não trava a fila (antes ficava em `pendentes/` e voltava sempre na frente).
A recusa por limite do importador (`"adiada": true`) não é recusa: essa linha e as seguintes ficam para o próximo envio.
Nada é apagado. Comando que falha, demora mais de 120 s ou responde algo que não é o JSON esperado: nada se move.

Corrida com o hook (sessão retomada que terminou durante o envio): o arquivo só se move se a marca
(`st_ino`, `st_mtime_ns`, `st_size`) ainda é a da leitura; depois de mover, o conteúdo é relido e comparado com a
linha enviada. Diferente (regravado entre a conferência e o rename): volta para `pendentes/` e vai no próximo envio.

SSH: com a chave só do envio (`ASSISTENTE_SSH_CHAVE` ou `~/.ssh/assistente_sessoes`, se existir), passa
`-i <chave> -o IdentitiesOnly=yes`; no i7, o `command=` do `authorized_keys` força o importador (ver README).

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
CHAVE_PADRAO = os.path.join("~", ".ssh", "assistente_sessoes")  # chave só do envio (README, "Envio para o i7")
DESTINO_VALIDO = re.compile(r"[A-Za-z0-9._@-]{1,200}")  # usuario@maquina; nunca começa com "-" (opção do ssh)


Marca = Tuple[int, int, int]  # (st_ino, st_mtime_ns, st_size): o rename atômico do hook troca o st_ino


class Pendente:
    """Um arquivo de `pendentes/` lido para o envio, com a marca do arquivo na hora da leitura."""

    def __init__(self, caminho: str, sessao: str, fim: Any, linha: bytes, marca: Marca) -> None:
        self.caminho = caminho
        self.sessao = sessao
        self.fim = fim
        self.linha = linha
        self.marca = marca


def _marca(caminho: str) -> Optional[Marca]:
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _linha(dado: Any) -> bytes:
    """Uma linha JSONL do resumo. ASCII: o surrogate solto e o acento atravessam o SSH sem depender do terminal."""
    return json.dumps(dado, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _linha_do_arquivo(caminho: str) -> Optional[bytes]:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return _linha(json.load(f))
    except (OSError, ValueError):
        return None


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
            candidatos.append((marca[1], caminho))
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
        linha = _linha(dado)
        if len(linha) > MAX_BYTES:
            fila.log("enviar: %s passa de 2 MB; fica em pendentes" % os.path.basename(caminho))
            continue
        if total + len(linha) > MAX_BYTES:
            return lote, len(caminhos) - indice
        total += len(linha)
        lote.append(Pendente(caminho, sessao, dado.get("fim"), linha, marca))
    return lote, 0


def chave_ssh() -> Optional[str]:
    """Caminho absoluto da chave só do envio: `ASSISTENTE_SSH_CHAVE` (precisa existir) ou a padrão, se existir."""
    definida = os.environ.get("ASSISTENTE_SSH_CHAVE", "").strip()
    if definida:
        caminho = os.path.abspath(os.path.expanduser(definida))
        if not os.path.isfile(caminho):
            raise ValueError("ASSISTENTE_SSH_CHAVE não aponta para um arquivo: %s" % caminho)
        return caminho
    padrao = os.path.abspath(os.path.expanduser(CHAVE_PADRAO))
    return padrao if os.path.isfile(padrao) else None


def comando_padrao() -> Optional[List[str]]:
    destino = os.environ.get("ASSISTENTE_SSH", "").strip()
    if not destino:
        return None
    if DESTINO_VALIDO.fullmatch(destino) is None or destino.startswith("-"):
        raise ValueError("ASSISTENTE_SSH inválida: use usuario@maquina")
    comando = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    chave = chave_ssh()
    if chave:
        comando += ["-i", chave, "-o", "IdentitiesOnly=yes"]
    # Com a chave restrita, o `command=` do authorized_keys força o importador e este comando é ignorado.
    return comando + [destino, COMANDO_REMOTO]


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


def _arquivar(pendente: Pendente, nome_pasta: str, motivo: Optional[str] = None) -> str:
    """Move o arquivo exato do lote para `enviadas/` ou `recusadas/`. Devolve "movida", "mudou" ou "erro".

    Só move se a marca ainda é a da leitura; depois de mover, relê e compara com a linha enviada. Se o hook regravou
    o arquivo entre a conferência e o rename, a versão nova volta para `pendentes/` (vai no próximo envio).
    """
    if _marca(pendente.caminho) != pendente.marca:
        fila.log("enviar: %s mudou durante o envio; fica em pendentes" % pendente.sessao)
        return "mudou"
    try:
        destino = fila.arquivar(pendente.caminho, nome_pasta, pendente.sessao, pendente.fim)
    except (OSError, ValueError) as e:
        fila.log("enviar: não movi %s para %s (%s)" % (pendente.sessao, nome_pasta, type(e).__name__))
        return "erro"
    if _linha_do_arquivo(destino) != pendente.linha:
        try:
            voltou = fila.devolver(destino, pendente.caminho)
        except OSError:
            voltou = False
        if voltou:
            fila.log("enviar: %s foi regravada durante o envio; a versão nova voltou para pendentes" % pendente.sessao)
        else:
            # Três gravações da mesma sessão dentro de um envio: a do meio já foi trocada por outra mais nova.
            fila.log("enviar: %s foi regravada duas vezes durante o envio; a versão do meio ficou em %s"
                     % (pendente.sessao, os.path.relpath(destino, fila.pasta_estado())))
        return "mudou"
    if motivo is not None:
        try:
            fila.anotar_motivo(destino, motivo)
        except OSError as e:
            fila.log("enviar: não gravei o motivo de %s (%s)" % (pendente.sessao, type(e).__name__))
    return "movida"


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
    recusas: Dict[int, str] = {}
    adiada_desde = len(lote) + 1  # a recusa por limite: dessa linha em diante, nada foi processado
    for recusa in resposta["recusadas"]:
        if not isinstance(recusa, dict) or type(recusa.get("linha")) is not int:
            continue
        if recusa.get("adiada") is True:
            adiada_desde = min(adiada_desde, recusa["linha"])
        else:
            recusas[recusa["linha"]] = " ".join(str(recusa.get("motivo")).split())[:200]
    movidas, recusadas, mudaram, adiadas = 0, 0, 0, 0
    for numero, pendente in enumerate(lote, start=1):
        if numero >= adiada_desde:
            adiadas += 1
        elif numero in recusas:
            fila.log("enviar: recusada %s: %s" % (pendente.sessao, recusas[numero]))
            situacao = _arquivar(pendente, "recusadas", recusas[numero])
            recusadas += situacao == "movida"
            mudaram += situacao == "mudou"
        elif pendente.sessao in no_banco:
            situacao = _arquivar(pendente, "enviadas")
            movidas += situacao == "movida"
            mudaram += situacao == "mudou"
    resumo = ("enviadas %d de %d (aceitas %d, repetidas %d), recusadas %d (em recusadas/ %d), mudaram no envio %d, "
              "ficaram para depois %d") % (
        movidas, len(lote), len(resposta["aceitas"]), len(resposta["repetidas"]), len(recusas), recusadas, mudaram,
        de_fora + adiadas)
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
