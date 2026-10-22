"""Fila local dos resumos de sessão, um arquivo JSON por sessão.

Pasta de estado: `ASSISTENTE_SESSOES_DIR`; senão, no Windows,
`%LOCALAPPDATA%\\assistente\\sessoes`; senão `~/.local/state/assistente/sessoes`.
- `pendentes/<projeto>/<sessao>.json`: ainda não enviados ao i7 (`enviar.py`).
- `enviadas/<projeto>/<sessao>.json`: já enviados. Nada é apagado (retenção: guardar tudo).
- `hooks.log`: erros e avisos dos hooks (cortado em ~1 MB, mantendo o fim).

`<projeto>` são os 12 primeiros dígitos do sha256 da raiz normalizada
(`chave_projeto`): dois repositórios com o mesmo nome de pasta não se misturam.
Arquivos no formato antigo (`pendentes/<sessao>.json`, sem subpasta) continuam
sendo lidos.

A chave contra duplicata é o id da sessão: gravar a mesma sessão de novo
(sessão retomada) substitui o arquivo em `pendentes/`.

Só biblioteca padrão; compatível com Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ID_VALIDO = re.compile(r"[A-Za-z0-9-]{8,80}")  # sempre com fullmatch
# Nomes que o Windows reserva (não podem virar nome de arquivo).
NOMES_RESERVADOS = re.compile(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])")
LIMITE_LOG = 1024 * 1024
MANTER_LOG = 512 * 1024
MAX_ARQUIVOS_LIDOS = 500  # `ultima_do_projeto` lê só os mais recentes do projeto, por data do arquivo
PASTAS = ("pendentes", "enviadas")


def pasta_estado() -> str:
    """Pasta de estado dos hooks de sessão."""
    definida = os.environ.get("ASSISTENTE_SESSOES_DIR", "").strip()
    if definida:
        return os.path.abspath(os.path.expanduser(definida))
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"], "assistente", "sessoes")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "assistente", "sessoes")


def id_valido(sessao: Any) -> bool:
    """Id de sessão aceito: 8 a 80 de `[A-Za-z0-9-]`, sem nome reservado do Windows."""
    return (
        isinstance(sessao, str)
        and ID_VALIDO.fullmatch(sessao) is not None
        and NOMES_RESERVADOS.fullmatch(sessao) is None
    )


def _conferir_id(sessao: Any) -> str:
    if not id_valido(sessao):
        raise ValueError("id de sessão inválido: %r" % (str(sessao)[:100],))
    return sessao


def raiz_normalizada(raiz: str) -> str:
    """Caminho absoluto normalizado (no Windows, sem diferença de maiúscula e barra)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(raiz)))


def chave_projeto(raiz: str) -> str:
    """Nome da subpasta do projeto: 12 primeiros dígitos do sha256 da raiz normalizada."""
    return hashlib.sha256(raiz_normalizada(raiz).encode("utf-8", errors="surrogatepass")).hexdigest()[:12]


def _gravar_atomico(destino: str, dados: bytes) -> None:
    pasta = os.path.dirname(destino)
    fd, temporario = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=pasta)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, destino)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def _copias(nome_pasta: str, sessao: str) -> List[str]:
    """Caminhos de `<sessao>.json` em `nome_pasta/` (formato antigo) e nas subpastas de projeto."""
    base = os.path.join(pasta_estado(), nome_pasta)
    achados = []
    plano = os.path.join(base, sessao + ".json")
    if os.path.isfile(plano):
        achados.append(plano)
    try:
        subpastas = os.listdir(base)
    except OSError:
        return achados
    for sub in subpastas:
        caminho = os.path.join(base, sub, sessao + ".json")
        if os.path.isfile(caminho):
            achados.append(caminho)
    return achados


def gravar(resumo: Dict[str, Any]) -> str:
    """Grava `pendentes/<projeto>/<sessao>.json` (substitui a mesma sessão). Devolve o caminho."""
    sessao = _conferir_id(resumo.get("sessao"))
    raiz = resumo.get("raiz")
    if not isinstance(raiz, str) or not raiz:
        raise ValueError("resumo sem raiz do projeto")
    pasta = os.path.join(pasta_estado(), "pendentes", chave_projeto(raiz))
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, sessao + ".json")
    # ensure_ascii: um surrogate solto (vindo de "\ud83d" no transcript) não derruba a gravação.
    dados = json.dumps(resumo, ensure_ascii=True, indent=1, sort_keys=True).encode("ascii")
    _gravar_atomico(destino, dados)
    # Sessão retomada noutra pasta: a cópia pendente antiga da mesma sessão sai da fila.
    for velho in _copias("pendentes", sessao):
        if os.path.abspath(velho) != os.path.abspath(destino):
            try:
                os.unlink(velho)
            except OSError:
                pass
    return destino


def marcar_enviada(sessao: str) -> List[str]:
    """Move a sessão de `pendentes/` para `enviadas/` (mesma subpasta). Devolve os caminhos novos."""
    _conferir_id(sessao)
    pendentes = os.path.join(pasta_estado(), "pendentes")
    movidos = []
    for origem in _copias("pendentes", sessao):
        relativo = os.path.relpath(origem, pendentes)
        destino = os.path.join(pasta_estado(), "enviadas", relativo)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        os.replace(origem, destino)
        movidos.append(destino)
    if not movidos:
        raise FileNotFoundError("sessão %s não está em pendentes" % sessao)
    return movidos


def _ler(caminho: str) -> Optional[Dict[str, Any]]:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def _vazia(resumo: Dict[str, Any]) -> bool:
    """Sessão aberta e fechada sem nada: sem título, sem arquivo, sem comando."""
    return not (resumo.get("titulo") or resumo.get("arquivos") or resumo.get("comandos"))


def _jsons(pasta: str) -> List[str]:
    try:
        nomes = os.listdir(pasta)
    except OSError:
        return []
    return [os.path.join(pasta, n) for n in nomes if n.endswith(".json") and not n.startswith(".")]


def ultima_do_projeto(
    raiz: str, maquina: str, exceto_sessao: Optional[str] = None, ignorar_vazias: bool = True
) -> Optional[Dict[str, Any]]:
    """A sessão mais recente (por `fim`) do projeto (pela raiz) nesta máquina, em pendentes e enviadas."""
    alvo = raiz_normalizada(raiz)
    chave = chave_projeto(raiz)
    candidatos: List[Tuple[float, int, str]] = []
    for ordem, nome_pasta in enumerate(PASTAS):
        base = os.path.join(pasta_estado(), nome_pasta)
        # Subpasta do projeto e, por compatibilidade, o formato antigo sem subpasta.
        for caminho in _jsons(os.path.join(base, chave)) + _jsons(base):
            try:
                candidatos.append((os.path.getmtime(caminho), -ordem, caminho))
            except OSError:
                continue
    candidatos.sort(reverse=True)

    vistas = set()
    melhor: Optional[Dict[str, Any]] = None
    for _, _, caminho in candidatos[:MAX_ARQUIVOS_LIDOS]:
        resumo = _ler(caminho)
        if resumo is None:
            continue
        sessao = resumo.get("sessao")
        # pendentes vem antes de enviadas na mesma data; a primeira cópia vale.
        if sessao in vistas:
            continue
        vistas.add(sessao)
        if sessao == exceto_sessao:
            continue
        raiz_resumo = resumo.get("raiz")
        if not isinstance(raiz_resumo, str) or raiz_normalizada(raiz_resumo) != alvo:
            continue
        if resumo.get("maquina") != maquina:
            continue
        if ignorar_vazias and _vazia(resumo):
            continue
        if melhor is None or str(resumo.get("fim") or "") > str(melhor.get("fim") or ""):
            melhor = resumo
    return melhor


def log(msg: str) -> None:
    """Acrescenta uma linha com data em `hooks.log`. Nunca levanta exceção."""
    try:
        pasta = pasta_estado()
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, "hooks.log")
        linha = "%s %s\n" % (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"), msg.replace("\n", " | "))
        with open(caminho, "a", encoding="utf-8", errors="backslashreplace") as f:
            f.write(linha)
        if os.path.getsize(caminho) > LIMITE_LOG:
            with open(caminho, "rb") as f:
                f.seek(-MANTER_LOG, os.SEEK_END)
                fim = f.read()
            fim = fim[fim.find(b"\n") + 1 :]
            _gravar_atomico(caminho, fim)
    except Exception:  # noqa: BLE001 - o log nunca derruba o hook
        pass
