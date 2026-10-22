"""Git do vault (2b.4): commit de cada escrita da IA, foto do estado antes de trocar, histórico de uma nota e o
conteúdo dela numa versão antiga.

Só chama o `git` do sistema por subprocess, com lista de argumentos (nunca shell), `-C <raiz>`, pathspec literal
(`*` e `[` no nome não viram padrão). Nenhuma config do repositório, do usuário ou do sistema pode rodar comando:
sem ganchos, sem fsmonitor, sem diff externo nem textconv, sem ssh, config global e de sistema desligadas, e caminho
com `filter` no .gitattributes não é comitado. Nada daqui grava conteúdo de nota em log ou mensagem.
Arquivo com cara de segredo (segredos.achar_segredo) não é comitado nem vira foto (Ficha 5, regra 5).
O repositório só conta se o `.git` está na raiz do vault: um vault dentro de outro repositório não é comitado.
Funções síncronas: quem chama do servidor roda numa thread (anyio.to_thread ou ferramenta síncrona do FastMCP).
"""

import hashlib
import logging
import os
import re
import signal
import stat
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .segredos import achar_segredo

log = logging.getLogger(__name__)

AUTOR = ("claude-app", "claude-app@localhost")
AUTOR_FOTO = ("vault", "vault@localhost")  # foto do que o dono deixou sem commit, antes da IA trocar
AUTOR_NOME, AUTOR_EMAIL = AUTOR
# Segundos por comando git: add e commit podem demorar num repositório grande; leitura não.
TIMEOUT_ESCRITA, TIMEOUT_LEITURA = 60, 15
SUBCOMANDOS_ESCRITA = {"add", "commit"}
ESPERA_TERMINO = 5  # depois do SIGTERM (o git apaga o index.lock), espera isto antes do SIGKILL
PRAZO_TRAVA = 30  # segundos esperando outro comando git deste processo; depois, desiste
ESPERAS_LOCK = (0.2, 0.5, 1.0)  # index.lock ocupado: espera e tenta de novo, até 3 vezes depois da primeira
REV_VALIDA = re.compile(r"[0-9a-f]{7,40}")
HISTORICO_PADRAO, HISTORICO_MAXIMO = 10, 50
TAMANHO_ID = 12
FUSO = ZoneInfo("America/Sao_Paulo")
# Bytes de uma versão antiga lidos no máximo (o limite de escrita é em caracteres; UTF-8 tem até 4 bytes cada).
LIMITE_BYTES = 4 * 200_000
_SEPARA_CAMPO, _SEPARA_LINHA = "\x1f", "\x1e"
# Config que, vinda do repositório, rodaria comando ou abriria rede. `-c` na linha de comando vence a do repositório.
CONFIG_SEGURA = (
    "core.hooksPath=/dev/null", "core.fsmonitor=false", "core.untrackedCache=false", "diff.external=",
    "core.sshCommand=false", "protocol.allow=never", "commit.gpgsign=false", "log.showSignature=false",
    "gc.auto=0",  # sem `gc --auto` depois do commit: o commit diário cuida
)
FILTRO_AUSENTE = {"unspecified", "unset"}

# Um comando git por vez neste processo: dois commits juntos brigariam pelo index.lock.
_trava_git = threading.Lock()


class SemGit(Exception):
    """O vault não tem repositório git na raiz."""


class ErroGit(Exception):
    """O git falhou (sem binário, timeout, código de saída, trava ocupada). A mensagem não tem conteúdo de nota."""


class VersaoInvalida(Exception):
    """A versão pedida não é um id hexadecimal, não existe ou não tem a nota com este caminho."""


class FotoFalhou(Exception):
    """O vault tem git, a nota tem mudança sem commit e a foto não saiu: a escrita da IA não pode seguir."""


class FotoComSegredo(FotoFalhou):
    """A nota a fotografar tem algo com cara de segredo: não vai para o histórico, e a escrita da IA não segue."""


@dataclass(frozen=True)
class VersaoNota:
    versao_git: str  # id completo do commit
    data: str  # AAAA-MM-DD HH:MM no fuso America/Sao_Paulo
    dados: bytes


def _ambiente() -> dict[str, str]:
    """Ambiente sem GIT_* herdada (GIT_DIR, GIT_WORK_TREE...) e sem config global nem de sistema."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return env


def _raiz_real(raiz: Path | str) -> Path:
    return Path(os.path.realpath(raiz))


@contextmanager
def _com_trava():
    """A trava do git deste processo, esperando até PRAZO_TRAVA segundos. ErroGit se não vier."""
    if not _trava_git.acquire(timeout=PRAZO_TRAVA):
        raise ErroGit(f"trava do git ocupada há {PRAZO_TRAVA} s")
    try:
        yield
    finally:
        _trava_git.release()


def _sinal(proc: subprocess.Popen, sinal: int) -> None:
    """Manda o sinal ao grupo do git (ele e o que ele chamou). Processo que já saiu: nada."""
    try:
        os.killpg(proc.pid, sinal)
    except (ProcessLookupError, PermissionError):
        pass


def _encerrar(proc: subprocess.Popen) -> None:
    """SIGTERM primeiro (o git apaga o index.lock ao sair), SIGKILL só depois de ESPERA_TERMINO segundos."""
    _sinal(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=ESPERA_TERMINO)
    except subprocess.TimeoutExpired:
        _sinal(proc, signal.SIGKILL)
        proc.wait()
    for f in (proc.stdout, proc.stderr):
        if f is not None:
            f.close()


def _git(raiz_real: Path, *args: str, autor: tuple[str, str] = AUTOR) -> subprocess.CompletedProcess:
    """Roda `git <args>` no vault. ErroGit se o binário falta ou passa do tempo; o código de saída fica com quem chama."""
    subcomando = args[0]
    timeout = TIMEOUT_ESCRITA if subcomando in SUBCOMANDOS_ESCRITA else TIMEOUT_LEITURA
    configs = [f"safe.directory={raiz_real}", f"user.name={autor[0]}", f"user.email={autor[1]}", *CONFIG_SEGURA]
    cmd = ["git", "-C", str(raiz_real), "--literal-pathspecs", "--no-pager"]
    for c in configs:
        cmd += ["-c", c]
    cmd += args
    try:
        # Sessão própria: no timeout o sinal vai para o git e para o que ele chamou, e não para o servidor.
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=_ambiente(), start_new_session=True)
    except FileNotFoundError:
        raise ErroGit("git não instalado") from None
    except OSError as e:
        raise ErroGit(type(e).__name__) from None
    try:
        saida, erro = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _encerrar(proc)
        raise ErroGit(f"git {subcomando} passou de {timeout} s") from None
    return subprocess.CompletedProcess(cmd, proc.returncode, saida, erro)


def _motivo(r: subprocess.CompletedProcess) -> str:
    """Primeira linha do erro do git, curta e só com caracteres imprimíveis (o git não põe conteúdo de nota ali)."""
    linhas = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
    primeira = "".join(c for c in (linhas[0] if linhas else "") if c.isprintable())
    return f"código {r.returncode}: {primeira[:200]}"


def repositorio(raiz: Path | str) -> Path | None:
    """Raiz real do vault se ela é a raiz de um repositório git; None se não há `.git` nela.

    `.git` numa pasta acima (vault dentro de outro repositório) não conta. ErroGit se o `.git` existe e o git falha.
    """
    raiz_real = _raiz_real(raiz)
    if not os.path.lexists(raiz_real / ".git"):
        return None
    r = _git(raiz_real, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        raise ErroGit(_motivo(r))
    topo = r.stdout.decode("utf-8", errors="surrogateescape").strip()
    return raiz_real if _raiz_real(topo) == raiz_real else None


def _lock_ocupado(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and b"index.lock" in r.stderr


def _filtro(raiz_real: Path, caminho: str) -> str | None:
    """Nome do `filter` que o .gitattributes põe no caminho; None sem filtro. O `git add` rodaria o comando dele."""
    r = _git(raiz_real, "check-attr", "-z", "filter", "--", caminho)
    if r.returncode != 0:
        raise ErroGit(_motivo(r))
    partes = r.stdout.split(b"\0")
    valor = partes[2].decode("utf-8", errors="replace") if len(partes) >= 3 else "unspecified"
    return None if valor in FILTRO_AUSENTE else valor


def _tentar_commit(raiz_real: Path, caminho: str, mensagem: str,
                   autor: tuple[str, str] = AUTOR) -> tuple[str, subprocess.CompletedProcess | None]:
    """('ok' | 'nada' | 'lock' | 'erro', resultado do passo que parou)."""
    r = _git(raiz_real, "add", "--", caminho)
    if r.returncode != 0:
        return ("lock" if _lock_ocupado(r) else "erro"), r
    # Só este caminho: o que mais estiver no index ou mudado no disco fica de fora.
    r = _git(raiz_real, "diff", "--cached", "--quiet", "--no-ext-diff", "--no-textconv", "--", caminho)
    if r.returncode == 0:
        return "nada", None
    if r.returncode != 1:
        return "erro", r
    r = _git(raiz_real, "commit", "--only", "--no-verify", "--quiet", "--no-edit", "-m", mensagem, "--", caminho,
             autor=autor)
    if r.returncode != 0:
        return ("lock" if _lock_ocupado(r) else "erro"), r
    return "ok", r


def _segredo_no_arquivo(raiz_real: Path, caminho: str) -> str | None:
    """Tipo do segredo no arquivo do disco (os bytes que o `git add` levaria), ou None. Arquivo que sumiu: None.

    Lê o arquivo de verdade (link simbólico: o alvo, que é o que o Obsidian mostra). ErroGit se não dá para ler.
    """
    try:
        dados = (raiz_real / caminho).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ErroGit(f"não consegui ler o arquivo para conferir segredo ({type(e).__name__})") from None
    return achar_segredo(dados.decode("utf-8", errors="replace"))


def _commitar(raiz_real: Path, caminho: str, mensagem: str, autor: tuple[str, str]) -> tuple[str, str]:
    """Commit só de `caminho`, com as esperas do index.lock. Chame com a trava.

    ('ok'|'nada'|'filtro'|'segredo'|'falhou', motivo). Com 'segredo', o motivo é o tipo, nunca o valor.
    """
    if (tipo := _segredo_no_arquivo(raiz_real, caminho)) is not None:
        return "segredo", tipo
    if _filtro(raiz_real, caminho) is not None:
        return "filtro", "o .gitattributes põe filter neste caminho e o filtro rodaria comando"
    for espera in (*ESPERAS_LOCK, None):
        situacao, r = _tentar_commit(raiz_real, caminho, mensagem, autor)
        if situacao in ("ok", "nada"):
            return situacao, ""
        if situacao == "lock" and espera is not None:
            time.sleep(espera)
            continue
        return "falhou", ("index.lock ocupado" if situacao == "lock" else _motivo(r))
    return "falhou", "index.lock ocupado"  # não chega aqui


def commitar(raiz: Path | str, caminho_relativo: str, mensagem: str) -> bool:
    """Comita só `caminho_relativo` (relativo à raiz do vault), autor claude-app. True se criou commit.

    Nunca levanta exceção: a escrita já valeu. Sem `.git` na raiz: DEBUG. Nada a comitar: não é erro.
    Arquivo com cara de segredo: não comita (WARNING sem o valor); o commit diário e o gitleaks decidem depois.
    Falha (git ausente, timeout, index.lock ocupado depois das esperas, trava ocupada, filtro, dono do repositório):
    WARNING sem conteúdo; o commit diário leva a mudança.
    """
    try:
        with _com_trava():
            raiz_real = repositorio(raiz)
            if raiz_real is None:
                log.debug("Vault sem .git na raiz: sem commit de %s", caminho_relativo)
                return False
            situacao, motivo = _commitar(raiz_real, caminho_relativo, mensagem, AUTOR)
    except ErroGit as e:
        situacao, motivo = "falhou", str(e)
    except Exception as e:  # nunca derruba a escrita
        situacao, motivo = "falhou", type(e).__name__
    if situacao == "ok":
        log.info("Commit no vault: %s", caminho_relativo)
        return True
    if situacao == "nada":
        log.debug("Nada a comitar em %s", caminho_relativo)
        return False
    if situacao == "segredo":
        log.warning("Escrita de %s ficou sem commit: o arquivo tem algo com cara de segredo.", caminho_relativo)
        return False
    log.warning("Commit do vault falhou em %s (%s); a escrita vale", caminho_relativo, motivo)
    return False


def _id_blob(dados: bytes, tamanho_id: int) -> str:
    """Id que o git daria a estes bytes como blob, sem filtro nenhum (sha1, ou sha256 no repositório sha256)."""
    h = hashlib.sha256() if tamanho_id == 64 else hashlib.sha1()  # noqa: S324 (é o id do git, não segurança)
    h.update(b"blob %d\0" % len(dados))
    h.update(dados)
    return h.hexdigest()


def _tem_commit(raiz_real: Path) -> bool:
    return _git(raiz_real, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0


def _precisa_foto(raiz_real: Path, caminho: str) -> bool:
    """O arquivo no disco tem mudança que o HEAD não guarda: modificado, ou não rastreado com conteúdo.

    Compara os bytes do disco com o blob do HEAD sem rodar git sobre o arquivo (nenhum filtro roda aqui).
    """
    arquivo = raiz_real / caminho
    try:
        st = os.lstat(arquivo)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    dados = arquivo.read_bytes()
    blob = None
    if _tem_commit(raiz_real):
        r = _git(raiz_real, "ls-tree", "-z", "HEAD", "--", caminho)
        if r.returncode != 0:
            raise ErroGit(_motivo(r))
        modo_tipo_id, _, nome = r.stdout.split(b"\0")[0].partition(b"\t")
        partes = modo_tipo_id.split()
        if nome and len(partes) == 3 and partes[1] == b"blob":
            blob = partes[2].decode()
    if blob is not None:
        return _id_blob(dados, len(blob)) != blob
    if not dados:
        return False
    # Não rastreado e ignorado pelo .gitignore: o git não guarda; não há foto a fazer.
    # (ls-files e não check-ignore: check-ignore não aceita --literal-pathspecs.)
    r = _git(raiz_real, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", caminho)
    if r.returncode != 0:
        raise ErroGit(_motivo(r))
    return not r.stdout.strip(b"\0")


def foto(raiz: Path | str, caminho_relativo: str, ferramenta: str) -> bool:
    """Antes de a IA trocar `caminho_relativo`: comita o que o dono deixou sem commit nele (autor vault).

    True se criou o commit da foto. Sem `.git` na raiz, ou nada a guardar: False.
    FotoFalhou se o vault tem `.git` e a foto não sai (git falhou, trava ocupada, filtro, index.lock preso);
    FotoComSegredo (uma FotoFalhou) se a nota tem algo com cara de segredo: não guarda isso no histórico.
    """
    mensagem = f"vault: estado antes de {ferramenta} {caminho_relativo}"
    try:
        with _com_trava():
            raiz_real = repositorio(raiz)
            if raiz_real is None or not _precisa_foto(raiz_real, caminho_relativo):
                return False
            situacao, motivo = _commitar(raiz_real, caminho_relativo, mensagem, AUTOR_FOTO)
    except ErroGit as e:
        situacao, motivo = "falhou", str(e)
    except OSError as e:
        situacao, motivo = "falhou", type(e).__name__
    if situacao == "ok":
        log.info("Foto no vault antes de %s: %s", ferramenta, caminho_relativo)
        return True
    if situacao == "nada":
        return False
    if situacao == "segredo":
        log.warning("Foto do vault recusada em %s: algo com cara de segredo (%s); %s recusada", caminho_relativo,
                    motivo, ferramenta)
        raise FotoComSegredo(motivo)
    log.warning("Foto do vault falhou em %s (%s); %s recusada", caminho_relativo, motivo, ferramenta)
    raise FotoFalhou(motivo)


def _data(segundos: str) -> str:
    return datetime.fromtimestamp(int(segundos), FUSO).strftime("%Y-%m-%d %H:%M")


def historico(raiz: Path | str, caminho_relativo: str, n: int = HISTORICO_PADRAO) -> list[dict]:
    """Versões da nota, da mais nova para a mais velha, seguindo troca de nome (`git log --follow`).

    Cada item traz o `caminho` que a nota tinha naquela versão e `restauravel` (só quando é o caminho atual).
    SemGit sem `.git` na raiz; ErroGit se o git falha. Nota sem histórico (ou repositório sem commit): lista vazia.
    """
    n = max(1, min(int(n), HISTORICO_MAXIMO))
    with _com_trava():
        raiz_real = repositorio(raiz)
        if raiz_real is None:
            raise SemGit
        if not _tem_commit(raiz_real):
            return []
        formato = _SEPARA_LINHA + _SEPARA_CAMPO.join(("%H", "%an", "%at", "%s"))
        r = _git(raiz_real, "log", "--follow", "--no-color", "--no-textconv", "--no-ext-diff", "-z", "--name-only",
                 "-n", str(n), f"--format={formato}", "--", caminho_relativo)
    if r.returncode != 0:
        raise ErroGit(_motivo(r))
    atual = caminho_relativo.encode("utf-8", errors="surrogateescape")
    versoes = []
    # Cada registro: \x1e<campos>\0\n<caminho>\0 (o caminho falta em commit de merge).
    for registro in r.stdout.split(_SEPARA_LINHA.encode())[1:]:
        cabecalho, _, resto = registro.partition(b"\0")
        partes = cabecalho.decode("utf-8", errors="replace").split(_SEPARA_CAMPO, 3)
        if len(partes) != 4:
            continue
        hash_, autor, quando, mensagem = partes
        nome = resto.lstrip(b"\n").split(b"\0")[0]
        versoes.append({"versao_git": hash_[:TAMANHO_ID], "autor": autor, "data": _data(quando),
                        "mensagem": mensagem, "caminho": nome.decode("utf-8", errors="replace") or None,
                        "restauravel": nome == atual})
    return versoes


def conteudo_em(raiz: Path | str, caminho_relativo: str, versao_git: str) -> VersaoNota:
    """Bytes da nota no commit `versao_git`, pelo caminho atual (nome antigo de antes de um `--follow` não vale).

    VersaoInvalida se o id não é hexadecimal (7 a 40), não acha o commit ou o commit não tem a nota neste caminho.
    """
    if not isinstance(versao_git, str) or not REV_VALIDA.fullmatch(versao_git):
        raise VersaoInvalida("versao_git inválida: use o id que historico_nota devolve (7 a 40 letras de 0-9 e a-f).")
    with _com_trava():
        raiz_real = repositorio(raiz)
        if raiz_real is None:
            raise SemGit
        r = _git(raiz_real, "log", "-1", "--no-color", "--no-textconv", f"--format=%H{_SEPARA_CAMPO}%at",
                 f"{versao_git}^{{commit}}", "--")
        if r.returncode != 0 or not r.stdout.strip():
            raise VersaoInvalida("Essa versão não existe no histórico do vault.")
        completo, quando = r.stdout.decode().strip().split(_SEPARA_CAMPO)
        objeto = f"{completo}:{caminho_relativo}"
        # Arquivo comum (100644 ou 100755) com exatamente este caminho; pasta, link simbólico ou ausente: recusa.
        r = _git(raiz_real, "ls-tree", "-z", completo, "--", caminho_relativo)
        entrada = r.stdout.split(b"\0")[0] if r.returncode == 0 else b""
        modo, _, resto = entrada.partition(b" ")
        nome = resto.partition(b"\t")[2].decode("utf-8", errors="surrogateescape")
        if modo not in (b"100644", b"100755") or nome != caminho_relativo:
            raise VersaoInvalida("Essa versão não tem a nota com este caminho. Se a nota mudou de nome, "
                                 "só vale a versão com \"restauravel\": true no historico_nota.")
        r = _git(raiz_real, "cat-file", "-s", objeto)
        if r.returncode != 0:
            raise ErroGit(_motivo(r))
        if int(r.stdout.strip()) > LIMITE_BYTES:
            raise VersaoInvalida("Essa versão da nota é maior que o limite: não dá para restaurar inteira.")
        # cat-file blob: os bytes guardados, sem filtro de texto (git show aplicaria textconv).
        r = _git(raiz_real, "cat-file", "blob", objeto)
    if r.returncode != 0:
        raise ErroGit(_motivo(r))
    return VersaoNota(versao_git=completo, data=_data(quando), dados=r.stdout)
