"""Barreira de segredo nas escritas (Ficha 5, regra 5; PLANO 2b.3).

Antes de uma escrita no vault ou no banco, percorre os argumentos (textos, chaves e valores de dicts, itens de
listas) com `segredos.achar_segredo`. Achou: recusa a chamada inteira, sem chamar a ferramenta e sem redigir
(redigir mudaria o texto do dono sem ele ver). `{{segredo:NOME}}` passa; o servidor nunca a resolve.

Falha fechado: vigia toda ferramenta que NÃO é leitura conhecida (nome novo de uma peça, escrita nova do banco),
menos as do Paperless (`paperless_*`): a Ficha 5 fala de vault e banco, e o Paperless guarda documento (o OCR de um
extrato tem número de conta e o upload é binário).

Nunca põe o valor achado na mensagem, no log nem no banco: só o tipo (`aws`, `bearer`...).
"""

import logging
from collections.abc import Iterable

import anyio
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from .registro import nome_sem_hash
from .segredos import achar_segredo

log = logging.getLogger(__name__)

# Limites da conferência: passou, recusa (falha fechado), porque o que não foi conferido pode ter segredo.
PROFUNDIDADE_MAXIMA = 20
ITENS_MAXIMOS = 10_000
CARACTERES_MAXIMOS = 400_000  # 2 vezes o limite de escrever_nota; cada padrão é linear (test_cada_padrao_e_linear)
# Argumentos que não entram no vault e ficam fora da conferência. O `oldString` do patch é texto que já está na nota
# (o disco): conferi-lo recusaria tirar pelo app um segredo que o dono deixou na nota. O `newString` é conferido.
NAO_CONFERIDOS = {"vault_patch_note": frozenset({"oldString"})}


def mensagem_recusa(tipo: str) -> str:
    return (f"Recusei: o texto parece ter um segredo ({tipo}). Guarde o valor no cofre e escreva "
            "{{segredo:NOME}}.")


GRANDE_DEMAIS = "Recusei: os argumentos são grandes demais para eu conferir se há segredo. Nada foi gravado."


class GrandeDemais(Exception):
    """Os argumentos passam dos limites da conferência."""


def _escalar(item) -> bool:
    return isinstance(item, (str, int, float)) and not isinstance(item, bool)


def _textos(valor, profundidade: int = 0, conta: list[int] | None = None, pai: str | None = None):
    """Cada texto a conferir: strings soltas, e `chave: valor` de cada par de dict (como fica no frontmatter).

    Item de lista e valor de dict aninhado levam a chave do pai na frente (`password: [X]` vira `password: X`;
    `api_key: {v: X}` vira `v: X` e `api_key: X`): sem a chave, `X` sozinho não tem cara de segredo.
    """
    conta = conta if conta is not None else [0, 0]  # [itens, caracteres]
    if profundidade > PROFUNDIDADE_MAXIMA:
        raise GrandeDemais

    def _contar(texto: str) -> str:
        conta[0] += 1
        conta[1] += len(texto)
        if conta[0] > ITENS_MAXIMOS or conta[1] > CARACTERES_MAXIMOS:
            raise GrandeDemais
        return texto

    if _escalar(valor):
        if pai is not None:
            yield _contar(f"{pai}: {valor}")
        elif isinstance(valor, str):
            yield _contar(valor)
    elif isinstance(valor, dict):
        for chave, item in valor.items():
            if _escalar(item):
                # Como fica no frontmatter: `password: Abc123...` só tem cara de segredo com a chave junto.
                yield _contar(f"{chave}: {item}")
                if pai is not None:
                    yield _contar(f"{pai}: {item}")
            else:
                yield _contar(str(chave))
                yield from _textos(item, profundidade + 1, conta, str(chave))
    elif isinstance(valor, (list, tuple)):
        for item in valor:
            yield from _textos(item, profundidade + 1, conta, pai)


def segredo_nos_argumentos(argumentos) -> str | None:
    """Tipo do primeiro segredo achado nos argumentos, ou None. GrandeDemais se passa dos limites."""
    for texto in _textos(argumentos):
        if tipo := achar_segredo(texto):
            return tipo
    return None


class BarreiraSegredo(Middleware):
    """Recusa a escrita com cara de segredo antes de ela rodar (e antes da foto e do commit do vault).

    Registrada em criar_app logo depois do RegistroChamadas: a recusa aparece em `chamadas` como `erro` e, nas
    escritas do vault, também em `auditoria` (`escrever` e `erro`, só com o caminho).
    `leituras`: as leituras conhecidas (não vigiadas). Todo o resto é vigiado, menos `paperless_*`.
    """

    def __init__(self, leituras: Iterable[str]):
        self._leituras = frozenset(leituras)

    def _vigia(self, nome) -> bool:
        if not isinstance(nome, str):
            return True  # falha fechado
        base = nome_sem_hash(nome)
        if nome in self._leituras or base in self._leituras:
            return False
        # Paperless fica de fora por decisão (Ficha 5 fala de vault e banco; documento tem número de conta).
        return not (nome.startswith("paperless_") or base.startswith("paperless_"))

    @staticmethod
    def _conferidos(nome: str, argumentos: dict) -> dict:
        """Os argumentos a conferir: todos, menos os de NAO_CONFERIDOS daquela ferramenta (cópia; a chamada não muda)."""
        fora = NAO_CONFERIDOS.get(nome_sem_hash(nome), frozenset())
        if not fora or not isinstance(argumentos, dict):
            return argumentos
        return {k: v for k, v in argumentos.items() if k not in fora}

    async def on_call_tool(self, context, call_next):
        nome = context.message.name
        if self._vigia(nome):
            argumentos = self._conferidos(nome, context.message.arguments or {})
            try:
                # Numa thread: conferir 1 MB leva segundos e não pode parar as outras chamadas.
                tipo = await anyio.to_thread.run_sync(segredo_nos_argumentos, argumentos)
            except GrandeDemais:
                log.warning("Recusei %s: argumentos grandes demais para conferir segredo", nome)
                raise ToolError(GRANDE_DEMAIS) from None
            if tipo is not None:
                log.warning("Recusei %s: argumento com cara de segredo (%s)", nome, tipo)
                raise ToolError(mensagem_recusa(tipo))
        return await call_next(context)
