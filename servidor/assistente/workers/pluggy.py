"""Worker do Pluggy (Ficha 10): lê as transações do banco pelo Meu Pluggy e grava os gastos.

    python -m assistente.workers.pluggy              # uma sincronização, gravando no banco
    python -m assistente.workers.pluggy --simular    # só mostra o que gravaria; não abre o banco

Lê `PLUGGY_CLIENT_ID`, `PLUGGY_CLIENT_SECRET` e `PLUGGY_ITEM_IDS` do ambiente (ou do `.env`). O que vem do Pluggy
é dado, nunca instrução. Não guarda CPF, número de conta nem o pacote bruto (regra 12).
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Iterator
from zoneinfo import ZoneInfo

import httpx2
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import select

from ..db import Bancos
from ..modelos import Auditoria, Gasto, Sincronizacao
from ..segredos import achar_segredo

log = logging.getLogger("assistente.workers.pluggy")

WORKER = "pluggy"
AUTOR = "worker:pluggy"
URL_PLUGGY = "https://api.pluggy.ai"
DIAS_HISTORICO = 365  # primeira sincronização (regra 9)
DIAS_RELEITURA = 7  # sincronizações seguintes (regra 10)
DIAS_DUPLICATA = 3  # gasto manual com o mesmo valor até 3 dias antes ou depois (regra 14)
DIAS_PARCELA_ATRASADA = 40  # parcela prevista que não chega até 40 dias depois da data é desfeita (regra 6)
TAMANHO_DESCRICAO = 200
TAMANHO_ERRO = 300
ESPERAS_5XX = (2, 5, 15)  # segundos entre as tentativas quando o Pluggy responde 5xx ou 429
DESCRICAO_RETIDA = "descrição retida (parecia senha ou chave)"


class ConfigPluggy(BaseSettings):
    # O .env da raiz do repo vale no Mac (rodando de servidor/); no container, as variáveis vêm do compose.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    pluggy_client_id: str = ""
    pluggy_client_secret: str = ""
    pluggy_item_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    pluggy_url: str = URL_PLUGGY
    # Nome que vai na forma de pagamento ("pix Nubank"); o item do Meu Pluggy não diz o banco de um jeito estável.
    pluggy_nome_banco: str = "Nubank"
    database_url_escrita: str = ""
    fuso: str = "America/Sao_Paulo"

    @field_validator("pluggy_item_ids", mode="before")
    @classmethod
    def _separar(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)

    def conferir(self) -> None:
        faltando = [n for n, v in (("PLUGGY_CLIENT_ID", self.pluggy_client_id),
                                   ("PLUGGY_CLIENT_SECRET", self.pluggy_client_secret),
                                   ("PLUGGY_ITEM_IDS", self.pluggy_item_ids)) if not v]
        if faltando:
            raise ErroPluggy(f"faltam no .env: {', '.join(faltando)} (docs/PLUGGY.md)")


class ErroPluggy(Exception):
    """Falha que vai para `sincronizacoes.erro`: texto curto, sem segredo nem dado do banco."""


# ---------------- Cliente da API ----------------


class ClientePluggy:
    """Só leitura: /auth, /items, /accounts, /categories e /v2/transactions."""

    def __init__(self, client_id: str, client_secret: str, url: str = URL_PLUGGY,
                 transporte: httpx2.BaseTransport | None = None):
        self._credenciais = {"clientId": client_id, "clientSecret": client_secret}
        self._http = httpx2.Client(base_url=url, timeout=30, transport=transporte)
        self._chave: str | None = None
        self._dormir = time.sleep

    def _entrar(self) -> None:
        try:
            r = self._http.post("/auth", json=self._credenciais)
        except httpx2.HTTPError as e:
            raise ErroPluggy(f"Pluggy fora do ar em /auth ({type(e).__name__})") from None
        if r.status_code != 200:
            raise ErroPluggy(f"Pluggy respondeu {r.status_code} em /auth: confira as chaves no .env")
        self._chave = r.json()["apiKey"]

    def _get(self, caminho: str, params: dict | None = None) -> dict:
        reentrou = False
        for espera in (*ESPERAS_5XX, None):
            if self._chave is None:
                self._entrar()
            try:
                r = self._http.get(caminho, params=params, headers={"X-API-KEY": self._chave})
            except httpx2.TransportError as e:
                if espera is None:
                    raise ErroPluggy(f"Pluggy fora do ar em {_rota(caminho)} ({type(e).__name__})") from None
                self._dormir(espera)
                continue
            if r.status_code in (401, 403) and not reentrou:  # a apiKey vale 2 horas
                self._chave, reentrou = None, True
                continue
            if r.status_code in (429, 500, 502, 503, 504) and espera is not None:  # o Pluggy dá 504 de vez em quando
                self._dormir(espera)
                continue
            if r.status_code != 200:
                raise ErroPluggy(f"Pluggy respondeu {r.status_code} em {_rota(caminho)}")
            return r.json()
        raise ErroPluggy(f"Pluggy não respondeu em {_rota(caminho)}")

    def item(self, item_id: str) -> dict:
        return self._get(f"/items/{item_id}")

    def itens(self) -> list[dict]:
        """GET /v2/items: a Pluggy deixa este desligado por padrão (opt-in por time); aí responde erro."""
        caminho, params, itens = "/v2/items", None, []
        while True:
            pagina = self._get(caminho, params)
            itens += pagina.get("results", [])
            proximo = pagina.get("next")
            if not (isinstance(proximo, str) and proximo.startswith("?")):
                return itens
            caminho = "/v2/items" + proximo

    def contas(self, item_id: str) -> list[dict]:
        return self._get("/accounts", {"itemId": item_id}).get("results", [])

    def categorias(self) -> list[dict]:
        return self._get("/categories").get("results", [])

    def transacoes(self, conta_id: str, desde: date, ate: date) -> Iterator[dict]:
        caminho, params = "/v2/transactions", {"accountId": conta_id, "dateFrom": desde.isoformat(),
                                                "dateTo": ate.isoformat()}
        while True:
            pagina = self._get(caminho, params)
            yield from pagina.get("results", [])
            proximo = pagina.get("next")
            if not proximo:
                return
            # `next` é a query pronta da página seguinte (docs da Pluggy: anexar ao caminho como veio).
            if not isinstance(proximo, str) or not proximo.startswith("?"):
                raise ErroPluggy("Pluggy devolveu um 'next' estranho em /v2/transactions")
            caminho, params = "/v2/transactions" + proximo, None

    def fechar(self) -> None:
        self._http.close()


def _rota(caminho: str) -> str:
    """Só o começo do caminho: id de item ou conta não vai para o log nem para o banco."""
    return "/" + caminho.strip("/").split("/")[0].split("?")[0]


# ---------------- Regras da Ficha 10 ----------------


def _normal(texto: str | None) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


# A categoria do Pluggy vem em `categoryId`, um código hierárquico (GET /categories, conferido em 2026-10-26):
# "19050001" = Transporte > Serviços automotivos > Postos de gasolina. Vale o prefixo mais longo da tabela.
# Fica de fora (regra 4):
_FORA_PREFIXO = (("04", "entre contas próprias"), ("0510", "pagamento de fatura"), ("03", "investimento"),
                 ("0601", "saldo bloqueado"))
# Categoria sugerida (regra 7); o que não casa vai para "outros" (impostos, taxas, empréstimos, seguros, doações).
_CATEGORIA_PREFIXO = (
    ("19050001", "combustível"), ("10", "alimentação"), ("11", "alimentação"), ("19", "transporte"),
    ("18", "saúde"), ("0703", "saúde"), ("2003", "saúde"), ("17", "casa"), ("0701", "casa"), ("2002", "casa"),
    ("0901", "lazer"), ("09", "assinaturas"), ("0702", "educação"), ("0806", "educação"), ("21", "lazer"),
    ("12", "lazer"), ("14", "lazer"), ("0704", "lazer"), ("08", "compras"), ("05", "transferência"),
)
# Sem `categoryId`: pela descrição da categoria e da transação.
_FORA_DESCRICAO = ((re.compile(r"\bpagamento (de |da )?(fatura|cartao)\b|\bcredit card payment\b"), "pagamento de fatura"),
                   (re.compile(r"\bsame person\b|\bmesma titularidade\b"), "entre contas próprias"),
                   (re.compile(r"\b(aplicacao|resgate)\b|\bcaixinha\b|\brdb\b|\binvest"), "investimento"))
_CATEGORIA_DESCRICAO = (
    ("combustível", ("gas station", "posto")), ("alimentação", ("grocer", "food", "eating", "supermercado")),
    ("transporte", ("transport", "taxi", "parking", "toll")), ("saúde", ("health", "pharmac", "farmacia")),
    ("casa", ("housing", "rent", "utilit")), ("assinaturas", ("streaming", "digital service")),
    ("educação", ("education",)), ("lazer", ("leisure", "travel", "ticket")), ("compras", ("shopping",)),
    ("transferência", ("transfer", "pix")),
)
CATEGORIA_PADRAO = "outros"
CATEGORIAS = tuple(dict.fromkeys(c for _, c in _CATEGORIA_PREFIXO)) + (CATEGORIA_PADRAO,)


def _pelo_prefixo(codigo: str, tabela: tuple[tuple[str, str], ...]) -> str | None:
    achados = [(len(p), valor) for p, valor in tabela if codigo.startswith(p)]
    return max(achados)[1] if achados else None

_PARCELA_NA_DESCRICAO = re.compile(r"\s*[-–]?\s*(parcela\s*)?\(?\d{1,2}\s*/\s*\d{1,2}\)?\s*$", re.IGNORECASE)
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class GastoNovo:
    id_externo: str
    data: date
    valor: Decimal
    descricao: str
    categoria: str
    forma_pagamento: str
    # Só a parcela que veio do banco (ou a transação comum) pode ser conferida e virar duplicata; a projetada não.
    real: bool = True


def motivo_fora(conta: dict, t: dict) -> str | None:
    """Por que a transação não vira gasto (regras 3 a 5), ou None se vira."""
    if t.get("status") not in (None, "POSTED"):
        return "pendente"
    if t.get("type") != "DEBIT":
        return "entrada"
    codigo = str(t.get("categoryId") or "")
    if codigo and (motivo := _pelo_prefixo(codigo, _FORA_PREFIXO)):
        return motivo
    texto = f"{_normal(t.get('category'))} | {_normal(t.get('description'))}"
    for padrao, motivo in _FORA_DESCRICAO:
        if padrao.search(texto):
            return motivo
    pagamento = t.get("paymentData") or {}
    pagador = ((pagamento.get("payer") or {}).get("documentNumber") or {}).get("value")
    recebedor = ((pagamento.get("receiver") or {}).get("documentNumber") or {}).get("value")
    if pagador and recebedor and _so_digitos(pagador) == _so_digitos(recebedor):
        return "entre contas próprias"
    if conta.get("type") == "BANK" and conta.get("subtype") not in (None, "CHECKING_ACCOUNT"):
        return "conta que não é corrente"
    return None


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def categoria_sugerida(t: dict) -> str:
    codigo = str(t.get("categoryId") or "")
    if codigo:
        return _pelo_prefixo(codigo, _CATEGORIA_PREFIXO) or CATEGORIA_PADRAO
    texto = _normal(t.get("category"))
    for categoria, chaves in _CATEGORIA_DESCRICAO:
        if any(chave in texto for chave in chaves):
            return categoria
    return CATEGORIA_PADRAO


def forma_de_pagamento(conta: dict, t: dict, banco: str) -> str:
    if conta.get("type") == "CREDIT":
        return f"cartão de crédito {banco}"
    tipo = _normal(t.get("operationType") or (t.get("paymentData") or {}).get("paymentMethod"))
    if "pix" in tipo:
        forma = "pix"
    elif "boleto" in tipo:
        forma = "boleto"
    elif any(x in tipo for x in ("ted", "doc", "tef", "transfer")):
        forma = "transferência"
    else:
        forma = "débito"
    return f"{forma} {banco}"


def _limpar(texto: str) -> str:
    return " ".join(_CONTROLE.sub(" ", texto).split())


def descricao_de(t: dict) -> str:
    """Descrição do banco e, se houver, a mensagem do Pix como pista (regra 8)."""
    descricao = _limpar(t.get("description") or t.get("descriptionRaw") or "sem descrição")
    mensagem = _limpar(((t.get("paymentData") or {}).get("reason")) or "")
    if mensagem and _normal(mensagem) not in _normal(descricao):
        descricao = f"{descricao} · {mensagem}"
    if achar_segredo(descricao):  # a mesma barreira das ferramentas (2b.3): texto de fora com cara de segredo
        return DESCRICAO_RETIDA
    return descricao[:TAMANHO_DESCRICAO]


def _data_local(texto: str, tz: ZoneInfo) -> date:
    momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if momento.tzinfo is None:
        return momento.date()
    return momento.astimezone(tz).date()


def _mais_meses(d: date, meses: int) -> date:
    ano, mes = divmod(d.month - 1 + meses, 12)
    ano, mes = d.year + ano, mes + 1
    for dia in range(d.day, 0, -1):  # 31/01 + 1 mês = 28 ou 29/02
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    raise AssertionError("inalcançável")


def converter(conta: dict, t: dict, banco: str, tz: ZoneInfo) -> tuple[list[GastoNovo], str | None]:
    """A transação vira gastos (mais de um quando é parcela: as futuras vêm junto, regra 6) ou um motivo de fora."""
    motivo = motivo_fora(conta, t)
    if motivo:
        return [], motivo
    valor = abs(Decimal(str(t.get("amountInAccountCurrency") or t["amount"]))).quantize(Decimal("0.01"))
    if valor == 0:
        return [], "valor zero"
    data = _data_local(t["date"], tz)
    categoria = categoria_sugerida(t)
    forma = forma_de_pagamento(conta, t, banco)
    cartao = t.get("creditCardMetadata") or {}
    numero, total = cartao.get("installmentNumber"), cartao.get("totalInstallments")
    if not (isinstance(numero, int) and isinstance(total, int) and 1 <= numero <= total and total > 1):
        return [GastoNovo(f"pluggy:{t['id']}", data, valor, descricao_de(t), categoria, forma)], None

    base = _PARCELA_NA_DESCRICAO.sub("", descricao_de(t)).strip() or "compra parcelada"
    compra = cartao.get("purchaseDate")
    inicio = _data_local(compra, tz) if compra else _mais_meses(data, -(numero - 1))
    # Com o valor da parcela em reais inteiros, para baixo: separa compras parceladas da mesma loja no mesmo dia (o
    # Nubank real tem três 12x no mesmo dia, 2026-10-27) e tolera os centavos de diferença entre as parcelas
    # (198,24 e 198,27). Sem o id da conta, que muda quando a conexão é refeita. Limite (Ficha 10, "Não faz"):
    # parcela que cruza o real inteiro (0,99 e 1,01) vira outra compra.
    chave = hashlib.sha256(f"{conta.get('type')}|{inicio.isoformat()}|{_normal(base)}|{total}|{int(valor)}".encode()).hexdigest()[:20]
    largura = max(2, len(str(total)))
    gastos = [
        GastoNovo(f"pluggy-parcela:{chave}:{k:0{largura}d}", _mais_meses(data, k - numero), valor,
                  f"{base} ({k:0{largura}d}/{total:0{largura}d})"[:TAMANHO_DESCRICAO], categoria, forma, real=(k == numero))
        for k in range(numero, total + 1)
    ]
    return gastos, None


# ---------------- Sincronização ----------------


@dataclass
class Resultado:
    novos: int
    ja_existiam: int
    fora: dict[str, int]
    primeira: bool
    previstas_desfeitas: int = 0


def ler(cliente: ClientePluggy, item_ids: list[str], desde: date, ate: date, banco: str,
        tz: ZoneInfo) -> tuple[list[GastoNovo], Counter]:
    gastos: list[GastoNovo] = []
    fora: Counter = Counter()
    for item_id in item_ids:
        item = cliente.item(item_id)
        if item.get("status") == "LOGIN_ERROR":
            raise ErroPluggy("a conexão do banco caiu (LOGIN_ERROR): renove no Meu Pluggy")
        for conta in cliente.contas(item_id):
            if conta.get("type") not in ("BANK", "CREDIT"):
                continue
            for t in cliente.transacoes(conta["id"], desde, ate):
                novos, motivo = converter(conta, t, banco, tz)
                if motivo:
                    fora[motivo] += 1
                gastos.extend(novos)
    # A mesma parcela pode vir duas vezes (a 3/10 projeta a 4/10, que também chega): fica a real, se houver.
    unicos: dict[str, GastoNovo] = {}
    for g in gastos:
        if g.id_externo not in unicos or (g.real and not unicos[g.id_externo].real):
            unicos[g.id_externo] = g
    return list(unicos.values()), fora


def gravar(bancos: Bancos, gastos: list[GastoNovo], primeira: bool) -> tuple[int, int]:
    """Grava os gastos novos com auditoria; o que já tem `id_externo` no banco fica como está (regra 11).

    A parcela real que chega no lugar da prevista tira a marca `previsto` e acerta a data e o valor (auditoria
    "confirmar", com os anteriores).
    """
    ids = [g.id_externo for g in gastos]
    novos = 0
    with bancos.escrita.begin() as s:
        existentes: dict[str, Gasto] = {}
        for i in range(0, len(ids), 500):
            existentes |= {g.id_externo: g for g in s.scalars(select(Gasto).where(Gasto.id_externo.in_(ids[i:i + 500])))}
        usados: set[int] = set()
        for g in gastos:
            if (atual := existentes.get(g.id_externo)) is not None:
                if g.real and atual.previsto:  # a previsão vira o fato: data e valor passam a ser os do banco
                    dados: dict = {"previsto": False}
                    if atual.data != g.data:
                        dados.update(data=g.data.isoformat(), data_anterior=atual.data.isoformat())
                        atual.data = g.data
                    if atual.valor != g.valor:
                        dados.update(valor=str(g.valor), valor_anterior=str(atual.valor))
                        atual.valor = g.valor
                    atual.previsto = False
                    s.add(Auditoria(ferramenta="worker_pluggy", tabela="gastos", registro_id=atual.id, acao="confirmar",
                                    dados=dados, autor=AUTOR))
                continue
            conferido = primeira or not g.real
            duplicata = _duplicata(s, g, usados, primeira) if g.real else None
            if duplicata is not None:
                conferido = False  # mesmo na primeira: o dono decide se repete
            registro = Gasto(data=g.data, valor=g.valor, descricao=g.descricao, categoria=g.categoria,
                             forma_pagamento=g.forma_pagamento, origem=WORKER, id_externo=g.id_externo,
                             conferido=conferido, duplicata_de=duplicata, previsto=not g.real)
            s.add(registro)
            s.flush()
            s.add(Auditoria(ferramenta="worker_pluggy", tabela="gastos", registro_id=registro.id, acao="criar",
                            dados={"data": g.data.isoformat(), "valor": str(g.valor), "descricao": g.descricao,
                                   "categoria": g.categoria, "forma_pagamento": g.forma_pagamento,
                                   "id_externo": g.id_externo, "conferido": conferido, "duplicata_de": duplicata,
                                   "previsto": not g.real},
                            autor=AUTOR))
            novos += 1
    return novos, len(gastos) - novos


def _duplicata(s, g: GastoNovo, usados: set[int], primeira: bool) -> int | None:
    """O gasto que este parece repetir (regra 14), ainda sem par: primeiro um manual com o mesmo valor até 3 dias antes
    ou depois; depois um do banco igual (data, valor, descrição e forma) com outro `id_externo`, como acontece quando a
    conexão é refeita e o Pluggy dá ids novos. Na primeira sincronização, só o segundo caso."""
    ja_ligados = select(Gasto.duplicata_de).where(Gasto.duplicata_de.is_not(None), Gasto.desfeito.is_(False))
    base = select(Gasto.id).where(Gasto.desfeito.is_(False), Gasto.previsto.is_(False), Gasto.valor == g.valor,
                                  Gasto.id.not_in(ja_ligados), Gasto.id.not_in(usados or {0}))
    candidato = None
    if not primeira:
        candidato = s.scalar(base.where(
            Gasto.origem == "manual", Gasto.data >= g.data - timedelta(days=DIAS_DUPLICATA),
            Gasto.data <= g.data + timedelta(days=DIAS_DUPLICATA)).order_by(Gasto.data, Gasto.id).limit(1))
    if candidato is None:
        candidato = s.scalar(base.where(
            Gasto.origem == WORKER, Gasto.data == g.data, Gasto.descricao == g.descricao,
            Gasto.forma_pagamento == g.forma_pagamento, Gasto.id_externo != g.id_externo).order_by(Gasto.id).limit(1))
    if candidato is not None:
        usados.add(candidato)
    return candidato


def desfazer_previstas_vencidas(bancos: Bancos, hoje: date) -> int:
    """Parcela prevista que não chegou do banco até 40 dias depois da data: a compra foi estornada ou cancelada.
    Desfaz ela e as seguintes da mesma compra, com auditoria (Ficha 10, regra 6). Nada é apagado."""
    limite = hoje - timedelta(days=DIAS_PARCELA_ATRASADA)
    desfeitas = 0
    with bancos.escrita.begin() as s:
        vencidas = s.scalars(select(Gasto).where(Gasto.origem == WORKER, Gasto.previsto.is_(True),
                                                 Gasto.desfeito.is_(False), Gasto.data < limite)).all()
        compras = {g.id_externo.rsplit(":", 1)[0] + ":" for g in vencidas if g.id_externo}
        for prefixo in sorted(compras):
            primeira_vencida = min(g.data for g in vencidas if g.id_externo.startswith(prefixo))
            for g in s.scalars(select(Gasto).where(Gasto.id_externo.startswith(prefixo, autoescape=True),
                                                   Gasto.previsto.is_(True), Gasto.desfeito.is_(False),
                                                   Gasto.data >= primeira_vencida)):
                g.desfeito = True
                s.add(Auditoria(ferramenta="worker_pluggy", tabela="gastos", registro_id=g.id, acao="desfazer",
                                dados={"motivo": "parcela prevista não chegou do banco"}, autor=AUTOR))
                desfeitas += 1
    return desfeitas


def _ultima_boa(bancos: Bancos) -> datetime | None:
    with bancos.escrita() as s:
        return s.scalar(select(Sincronizacao.inicio).where(Sincronizacao.worker == WORKER, Sincronizacao.ok.is_(True))
                        .order_by(Sincronizacao.inicio.desc()).limit(1))


def sincronizar(bancos: Bancos, cliente: ClientePluggy, cfg: ConfigPluggy, agora: datetime | None = None) -> Resultado:
    """Uma rodada: lê, grava e anota em `sincronizacoes` (ok ou o erro). Erro sobe depois de anotado."""
    tz = cfg.tz
    inicio = agora or datetime.now(tz)
    try:
        cfg.conferir()
        ultima = _ultima_boa(bancos)
        primeira = ultima is None
        hoje = inicio.astimezone(tz).date()
        if primeira:
            desde = hoje - timedelta(days=DIAS_HISTORICO)
        else:  # parado mais de 7 dias: lê desde a última boa, com 1 dia de folga (regra 10)
            if ultima.tzinfo is None:  # o SQLite (testes) devolve sem fuso o que gravou em UTC
                ultima = ultima.replace(tzinfo=timezone.utc)
            desde = min(hoje - timedelta(days=DIAS_RELEITURA), ultima.astimezone(tz).date() - timedelta(days=1))
        gastos, fora = ler(cliente, cfg.pluggy_item_ids, desde, hoje, cfg.pluggy_nome_banco, tz)
        novos, ja = gravar(bancos, gastos, primeira)
        desfeitas = desfazer_previstas_vencidas(bancos, hoje)
    except Exception as e:
        erro = str(e) if isinstance(e, ErroPluggy) else f"falha inesperada ({type(e).__name__})"
        _anotar(bancos, inicio, ok=False, novos=0, erro=erro[:TAMANHO_ERRO])
        raise
    _anotar(bancos, inicio, ok=True, novos=novos, erro=None)
    log.info("pluggy: %d novos, %d já existiam, %d parcelas previstas desfeitas, fora: %s%s", novos, ja, desfeitas,
             dict(fora), " (primeira)" if primeira else "")
    return Resultado(novos=novos, ja_existiam=ja, fora=dict(fora), primeira=primeira, previstas_desfeitas=desfeitas)


def _anotar(bancos: Bancos, inicio: datetime, ok: bool, novos: int, erro: str | None) -> None:
    try:
        with bancos.escrita.begin() as s:
            s.add(Sincronizacao(worker=WORKER, inicio=inicio, fim=datetime.now(timezone.utc), ok=ok, novos=novos,
                                erro=erro))
    except Exception as e:  # banco fora do ar: o log é o que sobra
        log.error("pluggy: não consegui anotar a sincronização (%s)", type(e).__name__)


# ---------------- Linha de comando ----------------


def simular(cliente: ClientePluggy, cfg: ConfigPluggy, dias: int) -> dict:
    """O que a primeira sincronização gravaria, sem banco. Sai com dado real: não vai para o repo nem para o log."""
    cfg.conferir()
    hoje = datetime.now(cfg.tz).date()
    gastos, fora = ler(cliente, cfg.pluggy_item_ids, hoje - timedelta(days=dias), hoje, cfg.pluggy_nome_banco, cfg.tz)
    return {"gastos": [{**asdict(g), "data": g.data.isoformat(), "valor": str(g.valor)} for g in gastos],
            "fora": dict(fora), "por_categoria": dict(Counter(g.categoria for g in gastos))}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # o INFO dele loga a URL, com id de item e de conta
    p = argparse.ArgumentParser(prog="python -m assistente.workers.pluggy", description=__doc__.split("\n")[0])
    p.add_argument("--simular", action="store_true", help="só mostra (JSON) o que gravaria; não abre o banco")
    p.add_argument("--dias", type=int, default=DIAS_HISTORICO, help="com --simular: quantos dias para trás")
    p.add_argument("--item", action="append", default=[],
                   help="confere se este id é uma conexão da aplicação (repita para testar vários); não grava nada")
    p.add_argument("--listar-itens", action="store_true", help="lista as conexões pelo /v2/items, se o time tiver ligado")
    args = p.parse_args(argv)
    cfg = ConfigPluggy()
    cliente = ClientePluggy(cfg.pluggy_client_id, cfg.pluggy_client_secret, cfg.pluggy_url)
    try:
        if args.listar_itens or args.item:
            if not (cfg.pluggy_client_id and cfg.pluggy_client_secret):
                raise ErroPluggy("faltam no .env: PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET (docs/PLUGGY.md)")
            if args.listar_itens:
                itens = cliente.itens()
            else:
                itens = []
                for item_id in args.item:
                    try:
                        itens.append(cliente.item(item_id))
                    except ErroPluggy as e:
                        itens.append({"id": item_id, "erro": str(e)})
            for i in itens:
                print(json.dumps({"id": i.get("id"), "conector": (i.get("connector") or {}).get("name"),
                                  "status": i.get("status"), "erro": i.get("erro")}, ensure_ascii=False))
            return 0
        if args.simular:
            json.dump(simular(cliente, cfg, args.dias), sys.stdout, ensure_ascii=False, indent=1)
            print()
            return 0
        if not cfg.database_url_escrita:
            raise ErroPluggy("falta DATABASE_URL_ESCRITA")
        bancos = Bancos.de_urls(cfg.database_url_escrita, cfg.database_url_escrita)
        sincronizar(bancos, cliente, cfg)
        return 0
    except ErroPluggy as e:
        log.error("pluggy: %s", e)
        return 1
    finally:
        cliente.fechar()


if __name__ == "__main__":
    sys.exit(main())
