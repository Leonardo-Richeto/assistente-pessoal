"""Ferramentas nossas sobre o vault (além do mcpvault): busca, leitura com versão, troca da nota inteira com versão,
histórico e restauração pelo git (vault_git.py), e o commit de cada escrita da IA, com uma foto antes de trocar
uma nota que o dono mudou sem commit.

Só aqui entra lógica do vault; a busca em si fica em vault_busca.py (sem FastMCP).
Escrita (escrever_nota): temporário na mesma pasta e os.replace, com a versão conferida duas vezes sob uma trava do
processo. Entre a segunda conferência e o os.replace, o Syncthing (ou o Obsidian) ainda pode escrever a nota, e essa
escrita se perde: risco aceito, porque a janela é de milissegundos.
"""

import hashlib
import logging
import os
import re
import secrets
import stat
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import anyio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from mcp.types import ToolAnnotations
from pydantic import Field

from . import vault_busca, vault_git
from .banco import Modelo, caminho_da_nota
from .segredos import achar_segredo
from .segredos_mcp import mensagem_recusa
from .vault_busca import LIMITE_PADRAO, IndiceVault

log = logging.getLogger(__name__)

LEITURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
TROCA = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

# Nomes para o registro (registro.py) e para o teste de classificação. Os próximos passos acrescentam.
LEITURAS_VAULT = {"buscar_vault", "ler_nota", "notas_recentes", "historico_nota"}
ESCRITAS_VAULT = {"escrever_nota", "restaurar_nota"}

# Caracteres: o máximo que ler_nota devolve e que escrever_nota aceita. Um limite só: a nota que ler_nota
# corta não pode voltar inteira por escrever_nota (perderia o fim).
LIMITE_CONTEUDO = 200_000
VERSAO_NOVA = "nova"
VERSAO_VALIDA = re.compile(r"[0-9a-f]{16}")
NOTA_MUDOU = "A nota mudou desde a leitura. Leia de novo com ler_nota."
_SO_EM_PARTE = ("Não dá para trocar a nota inteira; use vault_patch_note ou vault_write_note "
                "com mode append.")
AVISO_CORTADA = "Nota maior que o limite: lida só em parte. " + _SO_EM_PARTE
RECUSA_GRANDE = "Nota maior que o limite. " + _SO_EM_PARTE
AVISO_NAO_UTF8 = "A nota não está em UTF-8: só leitura. Edite no Obsidian."
VAZIO = "Conteúdo vazio: nada foi gravado. Nada se apaga no vault."
# Trava do mcpvault: write_note no modo padrão (overwrite) troca a nota inteira sem conferir versão.
# O nome com hash (`<hash12>_vault_write_note`, FastMCP 4.1.0) também conta, por garantia.
NOME_WRITE_NOTE = re.compile(r"(?:[0-9a-f]{12}_)?vault_write_note")
MODOS_ACRESCENTAR = {"append", "prepend"}
RECUSA_WRITE_NOTE = ("vault_write_note só acrescenta (mode append ou prepend). "
                     "Para trocar a nota inteira, use ler_nota e escrever_nota.")
LIMITE_RELACIONADAS = 10
RECENTES_PADRAO, RECENTES_MAXIMO = 10, 30
IGNORADOS_ESCRITA = {".git", ".obsidian", ".stversions", ".trash"}
FUSO = ZoneInfo("America/Sao_Paulo")
WIKILINK = re.compile(r"\[\[([^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")


class NotaMudou(ToolError):
    """A versão no disco não é a lida (outro aparelho escreveu no meio)."""


class NotaJaExiste(ToolError):
    """Criar com versao "nova", mas a nota já existe."""


class NotaSumiu(ToolError):
    """Trocar a nota, mas ela não existe (ou foi apagada no meio)."""


class NotaNaoTrocavel(ToolError):
    """A nota no disco está fora de UTF-8 ou passa do limite: só em parte (patch, append) ou no Obsidian."""


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


# Uma escrita por vez neste processo: a conferência da versão e a troca não se cruzam entre chamadas.
_trava_escrita = threading.Lock()


def _ler_bytes(real: Path) -> bytes:
    try:
        return real.read_bytes()
    except OSError:
        raise ToolError("Nota não existe ou não pode ser lida") from None


def _gravar_temporario(pasta: Path, dados: bytes, modo: int | None = None) -> Path:
    """Arquivo novo na mesma pasta, com nome `.escrever-nota-<hex>.tmp` (a busca e o lint só olham `.md`).

    Grava, aplica o modo (se dado) e faz fsync. Quem chama remove o temporário se ele sobrar.
    """
    tmp = pasta / f".escrever-nota-{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
            f.flush()
            if modo is not None:
                os.fchmod(f.fileno(), modo)
            os.fsync(f.fileno())
    except BaseException:
        _remover(tmp)
        raise
    return tmp


def _remover(caminho: Path) -> None:
    try:
        os.unlink(caminho)
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("Não consegui remover o temporário %s", caminho.name)


def _fsync_pasta(pasta: Path) -> None:
    """A troca de nome fica gravada no disco; onde não dá (Windows, alguns sistemas), segue sem."""
    try:
        fd = os.open(pasta, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _texto_trocavel(dados: bytes) -> None:
    """ToolError se a nota no disco não pode ser trocada inteira: fora de UTF-8 ou maior que o limite."""
    try:
        texto = dados.decode("utf-8")
    except UnicodeDecodeError:
        raise NotaNaoTrocavel(AVISO_NAO_UTF8) from None
    if len(texto) > LIMITE_CONTEUDO:
        raise NotaNaoTrocavel(RECUSA_GRANDE)


def _criar(raiz_real: Path, real: Path, limpo: str, dados: bytes) -> None:
    """Cria a nota sem sobrescrever: os.link do temporário falha se o destino já existe."""
    existe = (f"A nota já existe: {limpo}. Para acrescentar, use vault_write_note com mode append; "
              "não troque a nota inteira sem o dono pedir.")
    if os.path.lexists(real):
        raise NotaJaExiste(existe)
    pasta = real.parent
    pasta.mkdir(parents=True, exist_ok=True)
    # A pasta criada continua sendo ela mesma, dentro do vault (link simbólico posto no meio = recusa).
    if Path(os.path.realpath(pasta)) != pasta or not pasta.is_relative_to(raiz_real):
        raise ToolError("Caminho fora do vault")
    tmp = None
    try:
        tmp = _gravar_temporario(pasta, dados)
        try:
            os.link(tmp, real)
        except FileExistsError:
            raise NotaJaExiste(existe) from None
        except OSError:
            # Sistema sem link (alguns FUSE e montagens): "x" também falha se o arquivo já existe.
            try:
                f = open(real, "xb")
            except FileExistsError:
                raise NotaJaExiste(existe) from None
            try:
                with f:
                    f.write(dados)
                    f.flush()
                    os.fsync(f.fileno())
            except BaseException:
                _remover(real)  # foi esta chamada que criou
                raise
    finally:
        if tmp is not None:
            _remover(tmp)
    _fsync_pasta(pasta)


def _trocar(real: Path, limpo: str, dados: bytes, versao: str) -> None:
    """Troca a nota inteira se ela ainda tem `versao`; confere de novo logo antes do os.replace.

    Nota fora de UTF-8 ou maior que o limite não é trocada (ler_nota não devolve a versão dela).
    """
    if not real.is_file():
        raise NotaSumiu(f"Nota não existe: {limpo}")
    try:
        atual = real.read_bytes()
    except FileNotFoundError:
        raise NotaSumiu(f"Nota não existe: {limpo}") from None
    except OSError:
        raise ToolError("Nota não existe ou não pode ser lida") from None
    _texto_trocavel(atual)
    if versao_de(atual) != versao:
        raise NotaMudou(NOTA_MUDOU)
    modo = stat.S_IMODE(os.stat(real).st_mode)
    tmp = None
    try:
        tmp = _gravar_temporario(real.parent, dados, modo)
        try:
            de_novo = real.read_bytes()
        except FileNotFoundError:
            raise NotaSumiu(f"Nota não existe: {limpo}") from None
        if versao_de(de_novo) != versao:
            raise NotaMudou(NOTA_MUDOU)
        os.replace(tmp, real)
        tmp = None
    finally:
        if tmp is not None:
            _remover(tmp)
    _fsync_pasta(real.parent)


def gravar_nota(raiz: Path, caminho: str, conteudo: str, versao: str) -> dict:
    """Cria (versao "nova") ou troca a nota inteira, só se a versão no disco ainda é `versao`.

    Grava os bytes UTF-8 do conteúdo como vieram (fim de linha não muda). Nunca põe o conteúdo em mensagem.
    """
    real = caminho_seguro(raiz, caminho)
    limpo = caminho_da_nota(caminho)
    if not isinstance(conteudo, str):
        raise ToolError("conteudo precisa ser texto")
    if not conteudo.strip():
        raise ToolError(VAZIO)
    if len(conteudo) > LIMITE_CONTEUDO:
        raise ToolError(f"Conteúdo grande demais: até {LIMITE_CONTEUDO} caracteres. Nada foi gravado.")
    if "\x00" in conteudo:
        raise ToolError("Conteúdo com caractere nulo (NUL). Nada foi gravado.")
    try:
        dados = conteudo.encode("utf-8")
    except UnicodeEncodeError:
        raise ToolError("Conteúdo com caractere que não existe em UTF-8. Nada foi gravado.") from None
    versao = versao.strip() if isinstance(versao, str) else ""
    if versao != VERSAO_NOVA and not VERSAO_VALIDA.fullmatch(versao):
        raise ToolError('versao inválida: use a versao devolvida por ler_nota, ou "nova" para criar a nota.')
    raiz_real = Path(os.path.realpath(raiz))
    try:
        with _trava_escrita:
            if versao == VERSAO_NOVA:
                _criar(raiz_real, real, limpo, dados)
            else:
                _trocar(real, limpo, dados, versao)
    except OSError as e:
        log.warning("escrever_nota falhou em %s: %s", limpo, type(e).__name__)
        raise ToolError(f"Não consegui gravar {limpo}: {e.strerror or type(e).__name__}. Nada foi trocado.") from None
    if versao == VERSAO_NOVA:
        return {"caminho": limpo, "versao": versao_de(dados), "confirmacao": f"Criei {limpo}."}
    return {"caminho": limpo, "versao": versao_de(dados), "confirmacao": f"Reescrevi {limpo}."}


class TravaEscritaVault(Middleware):
    """vault_write_note só passa com mode append ou prepend; sem mode (overwrite) troca a nota sem versão.

    Registrada em criar_app depois do RegistroChamadas (mais por dentro): a recusa aparece na auditoria como
    `escrever` e depois `erro`, e a chamada nunca chega ao mcpvault.
    """

    async def on_call_tool(self, context, call_next):
        nome = context.message.name
        if isinstance(nome, str) and NOME_WRITE_NOTE.fullmatch(nome):
            modo = (context.message.arguments or {}).get("mode")
            if not (isinstance(modo, str) and modo in MODOS_ACRESCENTAR):
                raise ToolError(RECUSA_WRITE_NOTE)
        return await call_next(context)


# Escritas do mcpvault que viram commit (2b.4). manage_tags com operation=list só lê. Nome com hash também conta.
NOMES_COMMIT = re.compile(r"(?:[0-9a-f]{12}_)?(vault_write_note|vault_patch_note|vault_update_frontmatter"
                          r"|vault_manage_tags)")
SEM_GIT = "O vault não tem histórico (sem git)."
RECUSA_FOTO = "Não consegui guardar a versão atual no histórico; nada foi trocado."
RECUSA_FOTO_SEGREDO = ("A nota tem algo com cara de segredo; não guardo isso no histórico. Tire o segredo no Obsidian "
                       "e tente de novo.")
RESTAURAR_MUDOU = ("A nota mudou agora há pouco (outro aparelho). Nada foi trocado. Confira com o dono e tente "
                   "restaurar de novo.")
RESTAURAR_NAO_TROCAVEL = ("A nota atual não pode ser trocada pelo assistente (grande demais ou fora de UTF-8). "
                          "Nada foi trocado; restaure no Obsidian.")
# Extensões que o mcpvault 0.16.0 escreve (PathFilter.allowedExtensions). Só para o commit: as nossas ferramentas
# continuam só com .md (caminho_seguro).
EXTENSOES_COMMIT = (".md", ".markdown", ".txt", ".canvas", ".base")


def relativo_no_vault(raiz: Path, caminho: str) -> str:
    """Caminho do arquivo de verdade, relativo à raiz real (link simbólico dentro do vault: o alvo). ToolError se inválido."""
    real = caminho_seguro(raiz, caminho)
    return real.relative_to(Path(os.path.realpath(raiz))).as_posix()


def _proibido(partes) -> bool:
    """Pasta do sistema (.git, .obsidian, .stversions, .trash) em qualquer nível, sem caixa nem ponto/espaço no fim."""
    return any(p.rstrip(". ").casefold() in IGNORADOS_ESCRITA for p in partes)


def relativo_para_commit(raiz: Path, caminho) -> str | None:
    """Caminho que o mcpvault escreveu, relativo à raiz real, para o commit; None se não é seguro comitar.

    Normaliza como o `normalizePath` do mcpvault 0.16.0: tira espaço das pontas, troca `\\` por `/`, tira o caminho
    absoluto da raiz do começo (ou uma `/` inicial). Aceita as extensões que o mcpvault escreve. Recusa `..`, pasta do
    sistema e o que sai da raiz pelo realpath. Se o arquivo não existe com o nome dado, tenta as formas NFC e NFD.
    """
    if not isinstance(caminho, str):
        return None
    p = caminho.strip()
    if p == "~" or p.startswith("~/"):
        p = os.path.expanduser("~") + p[1:]
    normalizado = p.replace("\\", "/")
    raiz_real = Path(os.path.realpath(raiz))
    for prefixo in dict.fromkeys((raiz_real.as_posix(), Path(os.path.abspath(raiz)).as_posix())):
        if normalizado == prefixo:
            return None
        if normalizado.startswith(prefixo + "/"):
            p = normalizado[len(prefixo) + 1:]
            break
    else:
        if p.startswith("/"):
            p = p[1:]
    partes = p.split("/")
    if not p or not p.isprintable() or ".." in partes or _proibido(partes):
        return None
    if not p.lower().endswith(EXTENSOES_COMMIT):
        return None
    if not os.path.lexists(raiz_real / p):
        for forma in ("NFC", "NFD"):
            outra = unicodedata.normalize(forma, p)
            if os.path.lexists(raiz_real / outra):
                p = outra
                break
    real = Path(os.path.realpath(raiz_real / p))
    if not real.is_relative_to(raiz_real) or real == raiz_real:
        return None
    rel = real.relative_to(raiz_real)
    if _proibido(rel.parts) or not rel.name.lower().endswith(EXTENSOES_COMMIT):
        return None
    return rel.as_posix()


def commitar_escrita(raiz: Path, caminho: str, ferramenta: str) -> bool:
    """Commit só do arquivo escrito, mensagem `claude-app: <ferramenta> <caminho>`. Nunca levanta exceção."""
    rel = relativo_para_commit(raiz, caminho)
    if rel is None:
        log.warning("Escrita sem commit em %s: caminho que o commit não aceita (o commit diário decide)", ferramenta)
        return False
    return vault_git.commitar(raiz, rel, f"claude-app: {ferramenta} {rel}")


def foto_ou_recusa(raiz: Path, rel: str, ferramenta: str) -> None:
    """Guarda no git o que o dono deixou sem commit em `rel` antes de a IA trocar; ToolError se não conseguir."""
    try:
        vault_git.foto(raiz, rel, ferramenta)
    except vault_git.FotoComSegredo:
        raise ToolError(RECUSA_FOTO_SEGREDO) from None
    except vault_git.FotoFalhou:
        raise ToolError(RECUSA_FOTO) from None


class CommitPorEscrita(Middleware):
    """Escritas do mcpvault: foto do estado sem commit antes, commit só da nota do `path` depois (Ficha 5, regra 6).

    Antes de chamar a peça: se a nota tem mudança do dono sem commit, comita uma foto (autor vault); se a foto falha,
    recusa sem chamar a peça. Depois de uma escrita sem erro: commit da nota; falha no commit só vai para o log.
    escrever_nota e restaurar_nota fazem isso dentro da própria ferramenta (não passam por aqui).
    Registrada em criar_app depois da TravaEscritaVault (mais por dentro).
    """

    def __init__(self, raiz: Path):
        self._raiz = Path(raiz)

    async def on_call_tool(self, context, call_next):
        nome = context.message.name
        m = NOMES_COMMIT.fullmatch(nome) if isinstance(nome, str) else None
        argumentos = context.message.arguments or {}
        if m is None or (m[1] == "vault_manage_tags" and argumentos.get("operation") == "list"):
            return await call_next(context)
        caminho = argumentos.get("path")
        rel = relativo_para_commit(self._raiz, caminho)
        if rel is not None:
            await anyio.to_thread.run_sync(foto_ou_recusa, self._raiz, rel, m[1])
        resultado = await call_next(context)
        if getattr(resultado, "is_error", False) or not isinstance(caminho, str):
            return resultado
        with anyio.CancelScope(shield=True):  # a escrita já aconteceu
            await anyio.to_thread.run_sync(commitar_escrita, self._raiz, caminho, m[1])
        return resultado


def restaurar(raiz: Path, caminho: str, versao_git: str) -> dict:
    """Grava a nota como estava em `versao_git`, como versão nova, pelas mesmas regras de gravar_nota, e comita.

    Antes de trocar, guarda no git o que o dono deixou sem commit na nota (foto); sem foto, não troca.
    Versão com cara de segredo: recusa com a mensagem da barreira, sem o valor.
    """
    rel = relativo_no_vault(raiz, caminho)
    limpo = caminho_da_nota(caminho)
    try:
        antiga = vault_git.conteudo_em(raiz, rel, versao_git)
    except vault_git.SemGit:
        raise ToolError(SEM_GIT) from None
    except vault_git.VersaoInvalida as e:
        raise ToolError(str(e)) from None
    except vault_git.ErroGit as e:
        log.warning("restaurar_nota: git falhou em %s (%s)", rel, e)
        raise ToolError("Não consegui ler o histórico do vault. Nada foi trocado.") from None
    try:
        texto = antiga.dados.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError("Essa versão da nota não está em UTF-8: não dá para restaurar. Nada foi trocado.") from None
    # O conteúdo vem do git, não dos argumentos: a BarreiraSegredo não o viu (Ficha 5, regra 5).
    if (tipo := achar_segredo(texto)) is not None:
        log.warning("restaurar_nota recusada em %s: a versão tem algo com cara de segredo (%s)", rel, tipo)
        raise ToolError(mensagem_recusa(tipo))
    curta = antiga.versao_git[:vault_git.TAMANHO_ID]
    real = caminho_seguro(raiz, caminho)
    saida = {"caminho": limpo, "versao_git_restaurada": curta}
    try:
        if real.is_file():
            atual = _ler_bytes(real)
            if atual == antiga.dados:
                return {**saida, "versao": versao_de(atual), "confirmacao": "Nada mudou: a nota já está nessa versão."}
            _texto_trocavel(atual)
            foto_ou_recusa(raiz, rel, "restaurar_nota")
            gravada = gravar_nota(raiz, caminho, texto, versao_de(atual))
        else:
            gravada = gravar_nota(raiz, caminho, texto, VERSAO_NOVA)
    except (NotaMudou, NotaJaExiste, NotaSumiu):
        raise ToolError(RESTAURAR_MUDOU) from None
    except NotaNaoTrocavel:
        raise ToolError(RESTAURAR_NAO_TROCAVEL) from None
    vault_git.commitar(raiz, rel, f"claude-app: restaurar_nota {rel} ({curta})")
    return {**saida, "versao": gravada["versao"],
            "confirmacao": f"Restaurei {limpo} para a versão de {antiga.data}."}


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
        """Lê uma nota do vault inteira, com a versao (use em escrever_nota) e as notas ligadas a ela (links e backlinks), só com o resumo. Com aviso, a versao vem nula: não troque a nota inteira."""
        real = caminho_seguro(raiz, caminho)
        if not real.is_file():
            raise ToolError(f"Nota não existe: {caminho}")
        try:
            dados = real.read_bytes()
        except OSError:
            raise ToolError(f"Nota não existe: {caminho}") from None
        try:
            texto = dados.decode("utf-8")
            aviso = None
        except UnicodeDecodeError:  # só leitura: a troca gravaria o texto com � no lugar dos bytes originais
            texto = dados.decode("utf-8", errors="replace")
            aviso = AVISO_NAO_UTF8
        saida: dict = {"caminho": caminho_da_nota(caminho), "conteudo": texto, "versao": versao_de(dados)}
        if len(texto) > LIMITE_CONTEUDO:
            saida["conteudo"] = texto[:LIMITE_CONTEUDO]
            saida["cortado"] = True
            aviso = aviso or AVISO_CORTADA
        if aviso:  # sem versão: escrever_nota com o texto devolvido estragaria a nota
            saida["versao"] = None
            saida["aviso"] = aviso
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

    @mcp.tool(annotations=TROCA)
    def escrever_nota(
        caminho: Annotated[str, Field(description="Caminho da nota relativo ao vault (ex.: 00-inbox/ideia.md).")],
        conteudo: Annotated[str, Field(description="O texto inteiro da nota, com o frontmatter (até 200.000 caracteres).")],
        versao: Annotated[str, Field(description='A versao devolvida por ler_nota; "nova" para criar uma nota que não existe.')],
        modelo: Modelo = None,
    ) -> dict:
        """Troca a nota inteira, só se ela ainda tem a versao lida por ler_nota (ou versao "nova" para criar). Para acrescentar, use vault_write_note com mode append."""
        # Síncrona: o FastMCP roda numa thread (anyio.to_thread), e o git também.
        if not (isinstance(versao, str) and versao.strip() == VERSAO_NOVA):
            # Troca: antes, guarda no git o que o dono deixou sem commit na nota; sem a foto, não troca.
            foto_ou_recusa(raiz, relativo_no_vault(raiz, caminho), "escrever_nota")
        saida = gravar_nota(raiz, caminho, conteudo, versao)
        commitar_escrita(raiz, saida["caminho"], "escrever_nota")
        return saida

    @mcp.tool(annotations=LEITURA)
    def historico_nota(
        caminho: Annotated[str, Field(description="Caminho da nota relativo ao vault (ex.: 20-areas/perfil-do-leonardo.md).")],
        n: Annotated[int, Field(description="Quantas versões (1 a 50), da mais nova para a mais velha.")] = vault_git.HISTORICO_PADRAO,
    ) -> list[dict]:
        """Lista as versões antigas de uma nota no git do vault: versao_git (use em restaurar_nota), autor, data, mensagem, o caminho que a nota tinha naquela versão e restauravel (true só quando é o caminho atual; versão de nome antigo não se restaura)."""
        rel = relativo_no_vault(raiz, caminho)
        try:
            return vault_git.historico(raiz, rel, n)
        except vault_git.SemGit:
            raise ToolError(SEM_GIT) from None
        except vault_git.ErroGit as e:
            log.warning("historico_nota: git falhou em %s (%s)", rel, e)
            raise ToolError("Não consegui ler o histórico do vault.") from None

    @mcp.tool(annotations=TROCA)
    def restaurar_nota(
        caminho: Annotated[str, Field(description="Caminho atual da nota relativo ao vault.")],
        versao_git: Annotated[str, Field(description="O versao_git devolvido por historico_nota.")],
        modelo: Modelo = None,
    ) -> dict:
        """Volta a nota ao conteúdo de uma versão antiga, gravado como versão nova (nada se perde). Confirme com o dono antes."""
        return restaurar(raiz, caminho, versao_git)

    return mcp
