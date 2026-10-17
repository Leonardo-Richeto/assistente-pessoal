"""Registro de toda chamada de ferramenta (middleware do FastMCP no app principal).

Classificação falha fechado: só é leitura o que está numa lista explícita de leituras.
- Leitura conhecida (banco ou peça pronta): só log em INFO.
- Escrita do banco conhecida: só log; `_gravar` (banco.py) já grava a auditoria dos dados.
- Todo o resto (escrita de peça, nome novo, caminho por hash do FastMCP): linha `escrever` em
  `auditoria` ANTES da chamada e `ok`, `erro` ou `cancelado` depois, com `registro_id` apontando
  para a linha `escrever`. Sem a primeira linha, a chamada não roda.
- Ferramenta inexistente, escondida ou bloqueada: linha `negado`.

Nunca grava o conteúdo dos argumentos. Do vault, só o caminho da nota (`path`, `paths`,
`oldPath`, `newPath`). Do Paperless, só ids inteiros. A tabela `auditoria` é só INSERT.
"""

import logging
import re
from collections.abc import Iterable

import anyio
from fastmcp.exceptions import DisabledError, NotFoundError, ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from .db import Bancos
from .modelos import Auditoria

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

    async def _gravar_sem_falhar(self, *linha) -> None:
        """Depois da chamada: a escrita já aconteceu (ou foi negada); falha aqui só vai para o log.

        Blindado contra cancelamento: a chamada pode ter sido cancelada depois de escrever.
        """
        with anyio.CancelScope(shield=True):
            try:
                await self._gravar(*linha)
            except Exception:
                log.exception("Falha ao gravar auditoria %r de %r", linha[2], linha[0])

    async def on_call_tool(self, context, call_next):
        nome = nome_seguro(context.message.name)
        argumentos = context.message.arguments or {}
        autor = identidade() or ANONIMO
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

        try:
            resultado = await call_next(context)
        except (NotFoundError, DisabledError):
            log.warning("Chamada negada: %s autor=%s %s", nome, autor, dados)
            await self._gravar_sem_falhar(nome, tabela, "negado", dados, autor, id_escrita)
            raise
        except BaseException as e:
            # Cancelamento (CancelledError e afins) não é Exception: a escrita pode ter acontecido.
            situacao = "erro" if isinstance(e, Exception) else "cancelado"
            log.info("Chamada %s: %s autor=%s %s", nome, situacao, autor, dados)
            if escrita:
                await self._gravar_sem_falhar(nome, tabela, situacao, dados, autor, id_escrita)
            raise

        situacao = "erro" if getattr(resultado, "is_error", False) else "ok"
        log.info("Chamada %s: %s autor=%s %s", nome, situacao, autor, dados)
        if escrita:
            await self._gravar_sem_falhar(nome, tabela, situacao, dados, autor, id_escrita)
        return resultado
