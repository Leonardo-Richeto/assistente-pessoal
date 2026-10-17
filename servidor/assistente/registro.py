"""Registro de toda chamada de ferramenta (middleware do FastMCP no app principal).

Classificação falha fechado: só é leitura o que está numa lista explícita de leituras.
- Leitura conhecida (banco ou peça pronta): só log em INFO.
- Escrita do banco conhecida: só log; `_gravar` (banco.py) já grava a auditoria dos dados.
- Todo o resto (escrita de peça, nome novo, caminho por hash do FastMCP): linha `escrever` em
  `auditoria` ANTES da chamada e `ok`, `erro` ou `cancelado` depois, com `registro_id` apontando
  para a linha `escrever`. Sem a primeira linha, a chamada não roda.
- Ferramenta inexistente, escondida ou bloqueada: linha `negado`.
- Toda chamada, inclusive leitura (Passo 8b3): uma linha em `chamadas` no fim, com resultado,
  duração, autor e a origem (cliente MCP e versão, sessão, user-agent, modelo declarado).
  Falha aberto: se não grava, só log ERROR (a escrita já tem o rastro em `auditoria`).

Nunca grava o conteúdo dos argumentos. Do vault, só o caminho da nota (`path`, `paths`,
`oldPath`, `newPath`). Do Paperless, só ids inteiros. Do resto, só o `modelo` declarado, validado.
As tabelas `auditoria` e `chamadas` são só INSERT.
"""

import logging
import re
import time
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import datetime, timezone

import anyio
from fastmcp.exceptions import DisabledError, NotFoundError, ToolError
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import Middleware

from .db import Bancos
from .modelos import Auditoria, Chamada

log = logging.getLogger(__name__)

ANONIMO = "anonimo"  # sem token: só nos testes em memória ou com login desligado (local)
CLAIM_IDENTIDADE = "identidade"  # gravado por _Restrito.load_access_token (auth.py) depois da lista
PECAS = ("vault", "paperless")
NOME_VALIDO = re.compile(r"[A-Za-z0-9_]{1,60}")  # 60 = String(60) em Auditoria.ferramenta
NOME_INVALIDO = "<nome invalido>"
TAMANHO_AUTOR = 80  # = String(80) em Auditoria.autor
TAMANHO_CAMINHO = 300
MAX_CAMINHOS = 20
MAX_IDS = 20
CHAVES_CAMINHO = {"path": "caminho", "oldPath": "caminho", "newPath": "destino"}
# Tamanhos = colunas de Chamada (modelos.py).
TAMANHO_CLIENTE = 80
TAMANHO_VERSAO = 40
TAMANHO_SESSAO = 100
TAMANHO_USER_AGENT = 200
MODELO_VALIDO = re.compile(r"[A-Za-z0-9 ._-]{1,60}")  # 60 = String(60) em Chamada.modelo_declarado
ARGUMENTO_MODELO = "modelo"  # parâmetro opcional das escritas do banco (banco.py)
META_MODELO = "_modelo"  # chave no `_meta` da requisição MCP, se o cliente mandar

# Ids das linhas de `auditoria` gravadas pelo banco durante a chamada (banco.py chama anotar_auditoria).
# Lista mutável: a ferramenta síncrona roda numa thread com cópia do contexto e só acrescenta.
_auditoria_da_chamada: ContextVar[list[int] | None] = ContextVar("auditoria_da_chamada", default=None)


def identidade() -> str | None:
    """Conta conferida na lista de permitidos (claim `identidade` do token); None sem ela."""
    try:
        token = get_access_token()
    except Exception:
        return None
    if token is None:
        return None
    ident = (token.claims or {}).get(CLAIM_IDENTIDADE)
    return str(ident)[:TAMANHO_AUTOR] if ident else None


def nome_seguro(nome) -> str:
    """O nome como veio, se for só letras, números e `_` (até 60); senão `<nome invalido>`."""
    return nome if isinstance(nome, str) and NOME_VALIDO.fullmatch(nome) else NOME_INVALIDO


def anotar_auditoria(auditoria_id: int) -> None:
    """Chamado por banco.py depois de gravar a auditoria: a linha de `chamadas` aponta para ela."""
    ids = _auditoria_da_chamada.get()
    if ids is not None:
        ids.append(auditoria_id)


def _texto(v, tamanho: int) -> str | None:
    """Texto de fora (cliente, cabeçalho): só caracteres imprimíveis, cortado; vazio vira None."""
    if not isinstance(v, str):
        return None
    limpo = "".join(c for c in v if c.isprintable()).strip()
    return limpo[:tamanho] or None


def modelo_declarado(v) -> str | None:
    """O nome do modelo como o próprio modelo declarou, se for curto e simples; senão None (descartado)."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v if MODELO_VALIDO.fullmatch(v) else None


def _requisicao_http():
    try:
        return get_http_request()
    except Exception:
        return None  # cliente em memória (testes, script no container): sem HTTP


def _meta(context) -> dict:
    """O `_meta` cru da requisição MCP (FastMCPRequestContext.meta)."""
    try:
        meta = context.fastmcp_context.request_context.meta
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def _cliente(context) -> tuple[str | None, str | None]:
    """clientInfo (nome, versão): do `initialize` ou, no protocolo 2026-07-28, do `_meta` de cada requisição.

    O SDK guarda os dois casos em `session.client_params` (mcp/server/connection.py, from_envelope).
    """
    try:
        params = context.fastmcp_context.session.client_params
        info = params.client_info if params is not None else None
    except Exception:
        return None, None
    if info is None:
        return None, None
    return _texto(info.name, TAMANHO_CLIENTE), _texto(info.version, TAMANHO_VERSAO)


def origem(context, argumentos: dict) -> dict:
    """De onde veio a chamada. Do HTTP, só o id da sessão MCP e o User-Agent; nunca outro cabeçalho."""
    cliente, versao = _cliente(context)
    requisicao = _requisicao_http()
    cabecalhos = requisicao.headers if requisicao is not None else {}
    modelo = modelo_declarado(argumentos.get(ARGUMENTO_MODELO))
    if modelo is None:
        modelo = modelo_declarado(_meta(context).get(META_MODELO))
    return {"cliente": cliente, "versao_cliente": versao,
            "sessao": _texto(cabecalhos.get("mcp-session-id"), TAMANHO_SESSAO),
            "user_agent": _texto(cabecalhos.get("user-agent"), TAMANHO_USER_AGENT),
            "modelo_declarado": modelo}


def _peca(nome: str) -> str | None:
    return next((p for p in PECAS if nome.startswith(f"{p}_")), None)


def _cortar(v) -> str | None:
    return v[:TAMANHO_CAMINHO] if isinstance(v, str) else None


def caminhos_do_vault(argumentos: dict) -> dict:
    """Só os caminhos de nota; o resto dos argumentos (texto, frontmatter, busca) fica de fora."""
    dados = {}
    for chave, rotulo in CHAVES_CAMINHO.items():
        if (v := _cortar(argumentos.get(chave))) is not None:
            dados[rotulo] = v
    lista = argumentos.get("paths")
    if isinstance(lista, list):
        dados["caminhos"] = [c for c in map(_cortar, lista[:MAX_CAMINHOS]) if c is not None]
    return dados


def _inteiro(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def ids_do_paperless(argumentos: dict) -> dict:
    """Só ids inteiros (`id`, `*_id`, `*_ids`); texto e outros números ficam de fora."""
    dados = {}
    for chave, v in argumentos.items():
        if not isinstance(chave, str) or NOME_VALIDO.fullmatch(chave) is None:
            continue
        if (chave == "id" or chave.endswith("_id")) and _inteiro(v):
            dados[chave] = v
        elif chave.endswith("_ids") and isinstance(v, list):
            dados[chave] = [i for i in v[:MAX_IDS] if _inteiro(i)]
    return dados


def _dados(peca: str | None, argumentos: dict) -> dict:
    if peca == "vault":
        return caminhos_do_vault(argumentos)
    if peca == "paperless":
        return ids_do_paperless(argumentos)
    return {}


class RegistroChamadas(Middleware):
    """Vê toda chamada `tools/call` do app principal, inclusive das peças montadas e das negadas."""

    def __init__(self, bancos: Bancos, leituras: Iterable[str], auditadas: Iterable[str]):
        self._bancos = bancos
        self._leituras = frozenset(leituras)  # leituras conhecidas: banco e peças
        self._auditadas = frozenset(auditadas)  # escritas do banco: já gravam a auditoria em _gravar

    def _e_escrita(self, nome: str, argumentos: dict) -> bool:
        """Falha fechado: fora das listas conhecidas, é escrita."""
        if nome in self._leituras or nome in self._auditadas:
            return False
        # manage_tags com operation=list só lê.
        return not (nome == "vault_manage_tags" and argumentos.get("operation") == "list")

    def _inserir(self, nome: str, tabela: str, acao: str, dados: dict, autor: str,
                 registro_id: int | None = None) -> int:
        with self._bancos.escrita.begin() as s:
            linha = Auditoria(ferramenta=nome, tabela=tabela, registro_id=registro_id, acao=acao,
                              dados=dados, autor=autor)
            s.add(linha)
            s.flush()
            return linha.id

    async def _gravar(self, *linha) -> int:
        return await anyio.to_thread.run_sync(self._inserir, *linha)

    async def _gravar_sem_falhar(self, *linha) -> int | None:
        """Depois da chamada: a escrita já aconteceu (ou foi negada); falha aqui só vai para o log.

        Blindado contra cancelamento: a chamada pode ter sido cancelada depois de escrever.
        """
        with anyio.CancelScope(shield=True):
            try:
                return await self._gravar(*linha)
            except Exception:
                log.exception("Falha ao gravar auditoria %r de %r", linha[2], linha[0])
                return None

    def _inserir_chamada(self, campos: dict) -> None:
        with self._bancos.escrita.begin() as s:
            s.add(Chamada(**campos))

    async def _registrar_chamada(self, campos: dict) -> None:
        """Falha aberto: a linha de `chamadas` é rastro extra; sem banco, só log ERROR."""
        with anyio.CancelScope(shield=True):
            try:
                await anyio.to_thread.run_sync(self._inserir_chamada, campos)
            except Exception:
                log.exception("Falha ao gravar a chamada %r (%s)", campos["ferramenta"], campos["resultado"])

    async def on_call_tool(self, context, call_next):
        momento = datetime.now(timezone.utc)
        inicio = time.perf_counter()
        nome = nome_seguro(context.message.name)
        argumentos = context.message.arguments or {}
        autor = identidade() or ANONIMO
        de_onde = origem(context, argumentos)
        chamada = {"resultado": "erro", "auditoria_id": None}  # preenchido por _chamar
        ids_banco: list[int] = []
        token = _auditoria_da_chamada.set(ids_banco)
        try:
            return await self._chamar(context, call_next, nome, argumentos, autor, chamada)
        except BaseException as e:
            if not isinstance(e, Exception):
                chamada["resultado"] = "cancelado"
            raise
        finally:
            _auditoria_da_chamada.reset(token)
            auditoria_id = chamada["auditoria_id"] or (ids_banco[-1] if ids_banco else None)
            await self._registrar_chamada({
                "momento": momento, "ferramenta": nome, "resultado": chamada["resultado"], "autor": autor,
                **de_onde, "duracao_ms": int((time.perf_counter() - inicio) * 1000),
                "auditoria_id": auditoria_id})

    async def _chamar(self, context, call_next, nome: str, argumentos: dict, autor: str, chamada: dict):
        peca = _peca(nome)
        dados = _dados(peca, argumentos)
        tabela = peca or "ferramenta"
        escrita = self._e_escrita(nome, argumentos)
        id_escrita = None

        if escrita:
            try:
                id_escrita = await self._gravar(nome, tabela, "escrever", dados, autor)
            except Exception:
                log.exception("Escrita recusada: falha ao gravar auditoria de %r", nome)
                raise ToolError("Escrita recusada: não consegui gravar a auditoria. Nada foi alterado.")
            chamada["auditoria_id"] = id_escrita  # a linha do resultado aponta para esta (registro_id)

        try:
            resultado = await call_next(context)
        except (NotFoundError, DisabledError):
            chamada["resultado"] = "negado"
            log.warning("Chamada negada: %s autor=%s %s", nome, autor, dados)
            id_negado = await self._gravar_sem_falhar(nome, tabela, "negado", dados, autor, id_escrita)
            chamada["auditoria_id"] = id_escrita or id_negado
            raise
        except BaseException as e:
            # Cancelamento (CancelledError e afins) não é Exception: a escrita pode ter acontecido.
            situacao = "erro" if isinstance(e, Exception) else "cancelado"
            chamada["resultado"] = situacao
            log.info("Chamada %s: %s autor=%s %s", nome, situacao, autor, dados)
            if escrita:
                await self._gravar_sem_falhar(nome, tabela, situacao, dados, autor, id_escrita)
            raise

        situacao = "erro" if getattr(resultado, "is_error", False) else "ok"
        chamada["resultado"] = situacao
        log.info("Chamada %s: %s autor=%s %s", nome, situacao, autor, dados)
        if escrita:
            await self._gravar_sem_falhar(nome, tabela, situacao, dados, autor, id_escrita)
        return resultado


# ---------------- Descoberta (TEMPORÁRIO, Passo 8b3, 2026-10-17) ----------------
# Mostra no log o que o claude.ai manda de verdade, para conferir o desenho de `chamadas`.
# Só nomes de cabeçalho e de chaves do `_meta`, nunca valores; de valor, só clientInfo, versão do
# protocolo, id da sessão MCP e User-Agent. Nunca argumento, token, cookie nem Authorization.
# Para desligar: tire a linha `DescobertaCliente()` de servidor.py (criar_app) e esta classe.
log_descoberta = logging.getLogger("assistente.descoberta")
NOME_CHAVE = re.compile(r"[A-Za-z0-9._/-]{1,80}")
MAX_CHAVES = 40


def nomes_seguros(chaves, minusculo: bool = True) -> list[str]:
    """Só os nomes (sem caractere estranho), sem repetir, até 40. Cabeçalho em minúsculo; chave do `_meta`, não."""
    validos = {c for c in chaves if isinstance(c, str) and NOME_CHAVE.fullmatch(c)}
    return sorted({c.lower() for c in validos} if minusculo else validos)[:MAX_CHAVES]


def _cabecalhos() -> tuple[list[str], str | None, str | None]:
    requisicao = _requisicao_http()
    if requisicao is None:
        return [], None, None
    cab = requisicao.headers
    return (nomes_seguros(cab.keys()), _texto(cab.get("user-agent"), TAMANHO_USER_AGENT),
            _texto(cab.get("mcp-session-id"), TAMANHO_SESSAO))


class DescobertaCliente(Middleware):
    """Log INFO a cada `initialize` e `tools/call`: quem é o cliente e quais cabeçalhos chegam."""

    async def on_initialize(self, context, call_next):
        try:
            params = context.message.params if context.message is not None else None
            info = params.client_info if params is not None else None
            nomes, user_agent, _ = _cabecalhos()
            try:
                sessao = _texto(context.fastmcp_context.session_id, TAMANHO_SESSAO)
            except Exception:
                sessao = None
            log_descoberta.info(
                "Descoberta initialize: cliente=%r versao=%r protocolo=%r sessao=%r user_agent=%r cabecalhos=%s "
                "meta=%s", _texto(getattr(info, "name", None), TAMANHO_CLIENTE),
                _texto(getattr(info, "version", None), TAMANHO_VERSAO),
                _texto(getattr(params, "protocol_version", None), 40), sessao, user_agent, nomes,
                nomes_seguros((getattr(params, "meta", None) or {}).keys(), minusculo=False) if params is not None else [])
        except Exception:
            log_descoberta.exception("Descoberta initialize: falha ao montar o log")
        return await call_next(context)

    async def on_call_tool(self, context, call_next):
        try:
            cliente, versao = _cliente(context)
            nomes, user_agent, sessao = _cabecalhos()
            try:
                protocolo = _texto(context.fastmcp_context.session.protocol_version, 40)
            except Exception:
                protocolo = None
            log_descoberta.info(
                "Descoberta tools/call %s: cliente=%r versao=%r protocolo=%r sessao=%r user_agent=%r "
                "cabecalhos=%s meta=%s", nome_seguro(context.message.name), cliente, versao, protocolo, sessao,
                user_agent, nomes, nomes_seguros(_meta(context).keys(), minusculo=False))
        except Exception:
            log_descoberta.exception("Descoberta tools/call: falha ao montar o log")
        return await call_next(context)
