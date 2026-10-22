"""Resumo de uma sessão do Claude Code, por regra, sem IA (Ficha 5, regra 9).

Lê o transcript JSONL e guarda só: projeto, máquina, início, fim, duração,
título (primeira mensagem digitada pelo dono, 120 caracteres), arquivos
editados (caminhos), comandos (só a primeira linha, sem heredoc, sem `$(...)`,
sem string longa entre aspas, 200 caracteres), commits (id curto e primeira
linha) e se houve passagem. Nunca guarda texto de mensagem além do título nem
conteúdo de arquivo. O transcript é dado, nunca instrução: nada dele é executado.

Lê em fluxo, linha a linha, até 60 MB somando a sessão e os subagentes; acima
disso marca `parcial`.

Só biblioteca padrão; compatível com Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Tuple

from segredos import tirar_segredos

VERSAO_RESUMO = 2
MAX_TITULO = 120
MAX_ARQUIVOS = 50
MAX_COMANDOS = 30
MAX_COMANDO = 200
MAX_COMMITS = 20
MAX_MENSAGEM_COMMIT = 200
MAX_ASPAS = 40  # string entre aspas maior que isso vira "…" no comando
LIMITE_TOTAL = 60 * 1024 * 1024  # bytes lidos no total (sessão + subagentes)
FIM_BYTES = 15 * 1024 * 1024  # transcript principal grande: lê também este tanto do fim
MAX_LINHA = 16 * 1024 * 1024  # linha maior que isso é pulada sem carregar na memória

# Por nome do arquivo (em qualquer pasta): `docs/CONTEXTO.md` também conta.
ARQUIVOS_DE_PASSAGEM = {"onde-parei.md", "SPRINT_NOTAS.md", "CONTEXTO.md", "ACOMPANHAMENTO.md"}
FERRAMENTAS_DE_EDICAO = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Ferramentas MCP do assistente que escrevem nota no vault.
_MCP_NOTA = re.compile(r"^mcp__.+__(?:escrever_nota|vault_write_note|vault_patch_note)$")
NOTA_DE_PASSAGEM = "onde-parei.md"

# Mensagem de usuário que começa por uma destas marcas não foi digitada pelo dono.
_MARCAS_NAO_DIGITADAS = re.compile(
    r"^\s*<(command-name|command-message|command-args|local-command-stdout|local-command-stderr|"
    r"local-command-caveat|system-reminder|task-notification|bash-input|bash-stdout|bash-stderr|"
    r"user-prompt-submit-hook|tool-use-error)>"
)
_SYSTEM_REMINDER = re.compile(r"(?s)<system-reminder>.*?</system-reminder>")
# Saída do `git commit`: "[main abc1234] msg" ou "[main (root-commit) abc1234] msg".
_COMMIT = re.compile(r"^\[([^\]\s]+)(?: \([^)]*\))? ([0-9a-f]{7,40})\] (.+)$")
# `git log --oneline`: "abc1234 msg".
_ONELINE = re.compile(r"^([0-9a-f]{7,40}) (.+)$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
# `git commit`, `git -C pasta commit`, `git -c chave=valor commit`.
_GIT_COMMIT = re.compile(r"""\bgit(?:\s+-[Cc]\s+(?:"[^"]*"|'[^']*'|\S+))*\s+commit\b""")
_GIT_LOG_ONELINE = re.compile(r"""\bgit(?:\s+-[Cc]\s+(?:"[^"]*"|'[^']*'|\S+))*\s+log\b[^\n;|&]*--oneline""")
_SEM_COMMIT = ("nothing to commit", "nothing added to commit", "no changes added to commit")
# Qualquer string entre aspas, da esquerda para a direita (para parear certo); sem fechar, vai até o fim.
_ASPAS = re.compile(r""""(?:[^"\\]|\\.)*(?:"|$)|'[^']*(?:'|$)""")

_NOMES_PASSAGEM = "|".join(re.escape(n) for n in sorted(ARQUIVOS_DE_PASSAGEM))
_FIM_NOME = r"""["']?(?=$|[\s;|&)])"""
# Bash que grava num arquivo de passagem: `> X`, `>> X`, `tee [-a] X`, `sed -i ... X`.
_BASH_PASSAGEM = re.compile(
    r"""(?:>>?|\btee\s+(?:-a\s+)?)\s*["']?(?:[^\s"';|&<>]*/)?(?:%s)%s""" % (_NOMES_PASSAGEM, _FIM_NOME)
)
_SED_PASSAGEM = re.compile(
    r"""\bsed\s+(?:-[A-Za-z]+\s+)*-i\S*\s[^\n;|&]*?(?:^|[\s"'/])(?:%s)%s""" % (_NOMES_PASSAGEM, _FIM_NOME)
)


def nome_maquina() -> str:
    """`ASSISTENTE_MAQUINA` do ambiente, senão o nome curto do computador, minúsculo."""
    nome = os.environ.get("ASSISTENTE_MAQUINA", "").strip()
    if not nome:
        try:
            nome = socket.gethostname()
        except OSError:
            nome = ""
    nome = nome.split(".")[0].strip().lower()
    return nome or "desconhecida"


def achar_raiz(cwd: str) -> Tuple[str, str]:
    """(raiz, projeto): sobe a partir do cwd até achar `.git`; sem git, o próprio cwd."""
    inicio = os.path.abspath(cwd or os.getcwd())
    atual = inicio
    while True:
        if os.path.exists(os.path.join(atual, ".git")):
            break
        pai = os.path.dirname(atual)
        if pai == atual:
            atual = inicio
            break
        atual = pai
    projeto = os.path.basename(atual.rstrip("\\/")) or atual
    return atual, projeto


def _encurtar_aspas(m: "re.Match[str]") -> str:
    """String entre aspas com mais de 40 caracteres (sem contar as aspas) vira `"…"`."""
    texto = m.group(0)
    miolo = texto[1:-1] if len(texto) > 1 and texto[-1] == texto[0] else texto[1:]
    return '"…"' if len(miolo) > MAX_ASPAS else texto


def resumir_comando(comando: str) -> str:
    """Comando Bash sem conteúdo: primeira linha, até `<<` ou `$(`, sem string longa, sem segredo.

    Corta em 200 caracteres; se havia mais linhas, acrescenta ` [+N linhas]`.
    """
    linhas = comando.strip().splitlines()
    if not linhas:
        return ""
    primeira = linhas[0]
    corte = len(primeira)
    for marca in ("<<", "$("):
        i = primeira.find(marca)
        if i != -1:
            corte = min(corte, i)
    cortou = corte < len(primeira)
    primeira = _ASPAS.sub(_encurtar_aspas, primeira[:corte])
    primeira = " ".join(primeira.split())
    if cortou:
        primeira = (primeira + " …").strip()
    curto = tirar_segredos(primeira)[:MAX_COMANDO]
    if len(linhas) > 1:
        curto += " [+%d linhas]" % (len(linhas) - 1)
    return curto


def bash_grava_passagem(comando: str) -> bool:
    """A primeira linha do comando redireciona (`>`, `>>`, `tee`) ou faz `sed -i` num arquivo de passagem?"""
    linhas = comando.strip().splitlines()
    if not linhas:
        return False
    primeira = linhas[0]
    return bool(_BASH_PASSAGEM.search(primeira) or _SED_PASSAGEM.search(primeira))


class _Orcamento:
    """Bytes que ainda podem ser lidos (sessão principal e subagentes juntos)."""

    def __init__(self, total: int) -> None:
        self.restante = total
        self.cortou = False


def _proxima_linha(f: BinaryIO) -> Tuple[Optional[bytes], int]:
    """(linha, bytes lidos). Linha gigante é pulada (devolve b"") sem ficar na memória; fim: (None, 0)."""
    linha = f.readline(MAX_LINHA + 1)
    if not linha:
        return None, 0
    if len(linha) <= MAX_LINHA or linha.endswith(b"\n"):
        return linha, len(linha)
    lidos = len(linha)
    while True:
        resto = f.readline(1024 * 1024)
        lidos += len(resto)
        if not resto or resto.endswith(b"\n"):
            return b"", lidos


def _linhas(caminho: str, orcamento: _Orcamento, com_fim: bool = False) -> Iterator[bytes]:
    """Linhas do arquivo dentro do orçamento. Com `com_fim`, um arquivo grande demais tem lidos o
    começo e os últimos `FIM_BYTES` (onde fica a passagem e a hora do fim)."""
    try:
        tamanho = os.path.getsize(caminho)
        f = open(caminho, "rb")
    except OSError:
        return
    with f:
        if tamanho <= orcamento.restante:
            while True:
                linha, lidos = _proxima_linha(f)
                if linha is None:
                    return
                orcamento.restante -= lidos
                yield linha
        orcamento.cortou = True
        if orcamento.restante <= 0:
            return
        fim_bytes = FIM_BYTES if com_fim and orcamento.restante > 2 * FIM_BYTES else 0
        limite_comeco = orcamento.restante - fim_bytes
        lido = 0
        while True:
            linha, lidos = _proxima_linha(f)
            if linha is None or lido + lidos > limite_comeco:
                break
            lido += lidos
            yield linha
        if fim_bytes:
            f.seek(tamanho - fim_bytes)
            _proxima_linha(f)  # descarta a linha cortada pelo seek
            while True:
                linha, _ = _proxima_linha(f)
                if linha is None:
                    break
                yield linha
        orcamento.restante = 0


def _registros(caminho: str, orcamento: _Orcamento, com_fim: bool = False) -> Iterator[Dict[str, Any]]:
    """Objetos JSON do transcript, um por vez; linha quebrada é pulada."""
    for bruta in _linhas(caminho, orcamento, com_fim):
        bruta = bruta.strip()
        if not bruta:
            continue
        try:
            obj = json.loads(bruta.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def _data(texto: Any) -> Optional[datetime]:
    if not isinstance(texto, str) or not texto:
        return None
    t = texto.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        # 3.9 só aceita 3 ou 6 casas na fração; corta o que passar.
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(.*)$", t)
        if not m:
            return None
        fracao = (m.group(2) or "0")[:6].ljust(6, "0")
        try:
            d = datetime.fromisoformat("%s.%s%s" % (m.group(1), fracao, m.group(3)))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _texto_digitado(reg: Dict[str, Any]) -> Optional[str]:
    """Texto da mensagem se ela foi digitada pelo dono; senão None."""
    if reg.get("type") != "user" or reg.get("isMeta") or reg.get("isSidechain"):
        return None
    # Resumo de compactação ("This session is being continued...") não é do dono.
    if reg.get("isCompactSummary") or reg.get("isVisibleInTranscriptOnly"):
        return None
    if reg.get("toolUseResult") is not None:
        return None
    origem = reg.get("origin")
    if isinstance(origem, dict) and origem.get("kind") not in (None, "human"):
        return None
    if reg.get("promptSource") not in (None, "typed", "suggestion_accepted"):
        return None
    if reg.get("turnOrigin") not in (None, "human"):
        return None
    msg = reg.get("message")
    if not isinstance(msg, dict):
        return None
    conteudo = msg.get("content")
    partes: List[str] = []
    if isinstance(conteudo, str):
        partes = [conteudo]
    elif isinstance(conteudo, list):
        for item in conteudo:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_result":
                return None
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                partes.append(item["text"])
    for parte in partes:
        if _MARCAS_NAO_DIGITADAS.match(parte):
            continue
        limpo = " ".join(_SYSTEM_REMINDER.sub(" ", parte).split())
        if limpo:
            return limpo
    return None


def _caminho_curto(caminho: str, raiz: str) -> str:
    """Relativo à raiz quando dentro dela (com `/`); fora, absoluto com `~` no lugar da pasta pessoal."""
    try:
        absoluto = os.path.abspath(caminho)
        rel = os.path.relpath(absoluto, raiz)
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel.replace("\\", "/")
    except ValueError:  # Windows: outro disco
        absoluto = caminho
    casa = os.path.expanduser("~")
    if casa and absoluto.startswith(casa + os.sep):
        absoluto = "~" + absoluto[len(casa) :]
    return absoluto.replace("\\", "/")


def _nome_base(caminho: str) -> str:
    return caminho.replace("\\", "/").rstrip("/").split("/")[-1]


def _texto_resultado(item: Dict[str, Any]) -> str:
    conteudo = item.get("content")
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n".join(
            p.get("text", "") for p in conteudo if isinstance(p, dict) and isinstance(p.get("text"), str)
        )
    return ""


def _primeira_linha_util(texto: str) -> str:
    """Primeira linha não vazia que não seja de hook do git (começa com espaço ou `hint:`)."""
    for linha in texto.splitlines():
        if not linha.strip() or linha[:1].isspace() or linha.startswith("hint:"):
            continue
        return linha.rstrip()
    return ""


def _arquivos_subagentes(transcript_path: str) -> List[str]:
    """Transcripts dos subagentes: `<transcript sem .jsonl>/subagents/agent-*.jsonl`."""
    base = transcript_path[:-6] if transcript_path.endswith(".jsonl") else transcript_path
    pasta = os.path.join(base, "subagents")
    try:
        nomes = sorted(os.listdir(pasta))
    except OSError:
        return []
    return [os.path.join(pasta, n) for n in nomes if n.endswith(".jsonl")]


class _Coleta:
    """Junta arquivos, comandos e commits de um ou mais transcripts.

    Edição e passagem só contam quando o `tool_result` da mesma chamada chega sem erro.
    """

    def __init__(self, raiz: str) -> None:
        self.raiz = raiz
        self.arquivos: List[str] = []
        self.comandos: List[str] = []
        self.commits: List[Dict[str, str]] = []
        self.passagem = False
        self._ids_vistos: set = set()
        self._pendentes: Dict[str, Tuple[Optional[str], bool]] = {}  # id -> (caminho editado, é passagem)
        self._bash_commit: Dict[str, bool] = {}  # id do Bash com git commit -> tem `git log --oneline` depois
        self._resultados_vistos: set = set()

    def ferramenta(self, item: Dict[str, Any]) -> None:
        uid = item.get("id")
        if not isinstance(uid, str) or not uid or uid in self._ids_vistos:
            return
        self._ids_vistos.add(uid)
        nome = item.get("name")
        nome = nome if isinstance(nome, str) else ""
        entrada = item.get("input") if isinstance(item.get("input"), dict) else {}
        if nome in FERRAMENTAS_DE_EDICAO:
            caminho = entrada.get("file_path") or entrada.get("notebook_path")
            if isinstance(caminho, str) and caminho:
                self._pendentes[uid] = (caminho, _nome_base(caminho) in ARQUIVOS_DE_PASSAGEM)
        elif _MCP_NOTA.match(nome):
            caminho = entrada.get("caminho") or entrada.get("path")
            if isinstance(caminho, str) and _nome_base(caminho) == NOTA_DE_PASSAGEM:
                self._pendentes[uid] = (None, True)
        elif nome == "Bash":
            comando = entrada.get("command")
            if isinstance(comando, str) and comando.strip():
                m = _GIT_COMMIT.search(comando)
                if m:
                    self._bash_commit[uid] = bool(_GIT_LOG_ONELINE.search(comando, m.end()))
                if bash_grava_passagem(comando):
                    self._pendentes[uid] = (None, True)
                curto = resumir_comando(comando)
                if curto and curto not in self.comandos and len(self.comandos) < MAX_COMANDOS:
                    self.comandos.append(curto)

    def _somar_commit(self, commit_id: str, mensagem: str) -> None:
        commit_id = commit_id[:12]
        if len(self.commits) >= MAX_COMMITS or any(c["id"] == commit_id for c in self.commits):
            return
        self.commits.append({"id": commit_id, "mensagem": tirar_segredos(mensagem.strip())[:MAX_MENSAGEM_COMMIT]})

    def resultado(self, item: Dict[str, Any], reg: Dict[str, Any]) -> None:
        uid = item.get("tool_use_id")
        if not isinstance(uid, str) or uid in self._resultados_vistos:
            return
        pendente = self._pendentes.pop(uid, None)
        e_commit = uid in self._bash_commit
        if pendente is None and not e_commit:
            return
        self._resultados_vistos.add(uid)
        texto = _texto_resultado(item)
        extra = reg.get("toolUseResult")
        falhou = (
            item.get("is_error") is True
            or "<tool_use_error>" in texto
            or (isinstance(extra, str) and extra.startswith("Error"))
        )
        if falhou:
            return
        if pendente is not None:
            caminho, passagem = pendente
            if passagem:
                self.passagem = True
            if caminho:
                curto = _caminho_curto(caminho, self.raiz)
                if curto not in self.arquivos and len(self.arquivos) < MAX_ARQUIVOS:
                    self.arquivos.append(curto)
        if e_commit:
            self._commit(texto, extra, self._bash_commit[uid])

    def _commit(self, texto: str, extra: Any, tem_oneline: bool) -> None:
        """Commit de um Bash com `git commit` que deu certo (sem `is_error`)."""
        linha = _primeira_linha_util(texto)
        m = _COMMIT.match(linha)
        # Preferência: o sha que o Claude Code anota em toolUseResult.gitOperation.commit.
        operacao = extra.get("gitOperation") if isinstance(extra, dict) else None
        commit = operacao.get("commit") if isinstance(operacao, dict) else None
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if isinstance(sha, str) and _SHA.match(sha):
            mensagem = m.group(3) if m and (m.group(2).startswith(sha) or sha.startswith(m.group(2))) else ""
            self._somar_commit(sha, mensagem)
            return
        if any(frase in texto for frase in _SEM_COMMIT):
            return
        if m:
            self._somar_commit(m.group(2), m.group(3))
            return
        # `git commit -q && git log --oneline -1`: a primeira linha é o commit novo.
        if tem_oneline:
            m = _ONELINE.match(linha)
            if m:
                self._somar_commit(m.group(1), m.group(2))

    def registro(self, reg: Dict[str, Any]) -> None:
        tipo = reg.get("type")
        if tipo not in ("assistant", "user"):
            return
        msg = reg.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            return
        for item in msg["content"]:
            if not isinstance(item, dict):
                continue
            if tipo == "assistant" and item.get("type") == "tool_use":
                self.ferramenta(item)
            elif tipo == "user" and item.get("type") == "tool_result":
                self.resultado(item, reg)


def resumir(transcript_path: str, cwd: str, session_id: str, reason: str) -> Dict[str, Any]:
    """Resumo da sessão por regra (sem IA). Transcript ausente ou ruim: resume o que der."""
    raiz, projeto = achar_raiz(cwd)
    orcamento = _Orcamento(LIMITE_TOTAL)
    coleta = _Coleta(raiz)
    titulo = ""
    inicio: Optional[datetime] = None
    fim: Optional[datetime] = None
    if transcript_path and os.path.isfile(transcript_path):
        for reg in _registros(transcript_path, orcamento, com_fim=True):
            d = _data(reg.get("timestamp"))
            if d is not None:
                inicio = d if inicio is None or d < inicio else inicio
                fim = d if fim is None or d > fim else fim
            if not titulo:
                texto = _texto_digitado(reg)
                if texto:
                    titulo = tirar_segredos(texto)[:MAX_TITULO]
            coleta.registro(reg)

    if transcript_path:
        for sub in _arquivos_subagentes(transcript_path):
            if orcamento.restante <= 0:
                orcamento.cortou = True
                break
            for reg in _registros(sub, orcamento):
                coleta.registro(reg)

    duracao = 0
    if inicio is not None and fim is not None:
        duracao = int(round((fim - inicio).total_seconds() / 60.0))
    if fim is None:
        fim = datetime.now(timezone.utc)

    resumo: Dict[str, Any] = {
        "sessao": session_id,
        "projeto": projeto,
        "raiz": raiz,
        "maquina": nome_maquina(),
        "inicio": inicio.isoformat() if inicio else None,
        "fim": fim.isoformat(),
        "duracao_min": duracao,
        "titulo": titulo,
        "arquivos": coleta.arquivos,
        "comandos": coleta.comandos,
        "commits": coleta.commits,
        "passagem": coleta.passagem,
        "motivo_fim": reason or "",
        "versao_resumo": VERSAO_RESUMO,
    }
    if orcamento.cortou:
        resumo["parcial"] = True
    return resumo
