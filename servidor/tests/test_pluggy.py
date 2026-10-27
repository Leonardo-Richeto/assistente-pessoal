"""Worker do Pluggy e ferramentas de conferência (Ficha 10, PLANO 3.3 e 3.4).

Respostas do Pluggy SINTÉTICAS, no formato do /v2/transactions (docs.pluggy.ai): nunca dado real no repo.
A API falsa roda num httpx2.MockTransport; o banco é SQLite (ou TEST_DATABASE_URL).
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastmcp import Client
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from assistente import vault
from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from assistente.modelos import Auditoria, Base, Gasto, Sincronizacao
from assistente.workers import pluggy
from assistente.workers.__main__ import proximo_horario

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 10, 26, 6, 0, tzinfo=TZ)
CPF = "000.000.000-00"  # sintético

CONTA_CORRENTE = {"id": "conta-cc", "type": "BANK", "subtype": "CHECKING_ACCOUNT"}
CONTA_POUPANCA = {"id": "conta-pp", "type": "BANK", "subtype": "SAVINGS_ACCOUNT"}
CARTAO = {"id": "conta-cartao", "type": "CREDIT", "subtype": "CREDIT_CARD"}

# Códigos e nomes como o GET /categories da Pluggy devolve (conferido em 2026-10-26).
CATEGORIAS = [
    {"id": "05070000", "description": "Transfer - PIX"},
    {"id": "05090004", "description": "Third party transfer - PIX"},
    {"id": "04020000", "description": "Same person transfer - PIX"},
    {"id": "05100000", "description": "Credit card payment"},
    {"id": "03010000", "description": "Automatic investment"},
    {"id": "10000000", "description": "Groceries"},
    {"id": "11020000", "description": "Food delivery"},
    {"id": "19050001", "description": "Gas stations"},
    {"id": "19050002", "description": "Parking"},
    {"id": "09010000", "description": "Gaming"},
    {"id": "09020000", "description": "Video streaming"},
    {"id": "07010001", "description": "Internet"},
    {"id": "200300000", "description": "Health insurance"},
    {"id": "15010000", "description": "Income taxes"},
    {"id": "08000000", "description": "Shopping"},
]


def _t(id, valor, dia, categoria_id=None, tipo="DEBIT", status="POSTED", descricao="Compra", **extra) -> dict:
    nomes = {c["id"]: c["description"] for c in CATEGORIAS}
    return {"id": id, "description": descricao, "amount": valor, "date": f"{dia}T03:00:00.000Z", "type": tipo,
            "status": status, "category": nomes.get(categoria_id), "categoryId": categoria_id,
            "currencyCode": "BRL", **extra}


def _pix(id, valor, dia, mensagem=None, recebedor="111.111.111-11", **extra) -> dict:
    return _t(id, valor, dia, "05070000", descricao="Transferência enviada pelo Pix", operationType="PIX",
              paymentData={"payer": {"documentNumber": {"type": "CPF", "value": CPF}},
                           "receiver": {"documentNumber": {"type": "CPF", "value": recebedor}},
                           "reason": mensagem, "paymentMethod": "PIX"}, **extra)


def _parcela(id, valor, dia, n, total, descricao="Loja Sintética", compra="2026-09-10T03:00:00.000Z") -> dict:
    return _t(id, valor, dia, "08000000", descricao=f"{descricao} - Parcela {n}/{total}",
              creditCardMetadata={"installmentNumber": n, "totalInstallments": total, "purchaseDate": compra,
                                  "totalAmount": float(Decimal(str(valor)) * total)})


class ApiFalsa:
    """Pluggy de mentira: /auth, /items, /accounts, /categories e /v2/transactions com páginas de 2."""

    def __init__(self, transacoes: dict[str, list[dict]], status_auth=200, status_item="UPDATED"):
        self.transacoes = transacoes
        self.status_auth = status_auth
        self.status_item = status_item
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(req)
        caminho = req.url.path
        if caminho == "/auth":
            corpo = json.loads(req.content)
            assert corpo == {"clientId": "id-teste", "clientSecret": "segredo-teste"}
            if self.status_auth != 200:
                return httpx2.Response(self.status_auth, json={"message": "unauthorized"})
            return httpx2.Response(200, json={"apiKey": "chave-api"})
        assert req.headers.get("X-API-KEY") == "chave-api"
        if caminho.startswith("/items/"):
            return httpx2.Response(200, json={"id": caminho.split("/")[-1], "status": self.status_item,
                                              "connector": {"name": "MeuPluggy"}})
        if caminho == "/accounts":
            return httpx2.Response(200, json={"results": [CONTA_CORRENTE, CONTA_POUPANCA, CARTAO]})
        if caminho == "/categories":
            return httpx2.Response(200, json={"results": CATEGORIAS})
        if caminho == "/v2/transactions":
            conta = req.url.params["accountId"]
            todas = self.transacoes.get(conta, [])
            inicio = int(req.url.params.get("after") or 0)
            pagina = todas[inicio:inicio + 2]
            proximo = f"?accountId={conta}&after={inicio + 2}" if inicio + 2 < len(todas) else None
            return httpx2.Response(200, json={"results": pagina, "next": proximo})
        return httpx2.Response(404)

    def desdes(self) -> set[str]:
        return {r.url.params["dateFrom"] for r in self.pedidos if r.url.path == "/v2/transactions"
                and "dateFrom" in r.url.params}


def _cfg(**extra) -> pluggy.ConfigPluggy:
    base = dict(pluggy_client_id="id-teste", pluggy_client_secret="segredo-teste", pluggy_item_ids="item-1")
    return pluggy.ConfigPluggy(_env_file=None, **{**base, **extra})


def _cliente(api: ApiFalsa) -> pluggy.ClientePluggy:
    return pluggy.ClientePluggy("id-teste", "segredo-teste", "https://api.pluggy.teste", httpx2.MockTransport(api))


@pytest.fixture
def url(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'teste.db'}"
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return url


@pytest.fixture
def bancos(url):
    return Bancos.de_urls(url, url)


def _gastos(url) -> list[Gasto]:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(Gasto).order_by(Gasto.data, Gasto.id)))


def _sincronizar(bancos, api, agora=AGORA, **cfg):
    return pluggy.sincronizar(bancos, _cliente(api), _cfg(**cfg), agora=agora)


# ---------------- Regras de conversão ----------------


def _converter(t, conta=CONTA_CORRENTE):
    return pluggy.converter(conta, t, "Nubank", TZ)


@pytest.mark.parametrize("t,conta,motivo", [
    (_t("p", -10, "2026-10-20", status="PENDING"), CONTA_CORRENTE, "pendente"),
    (_t("e", 3000, "2026-10-05", tipo="CREDIT", descricao="Salário"), CONTA_CORRENTE, "entrada"),
    (_t("es", -50, "2026-10-05", tipo="CREDIT", descricao="Estorno"), CARTAO, "entrada"),
    (_t("f", -2300, "2026-10-10", "05100000", descricao="Pagamento de fatura"), CONTA_CORRENTE, "pagamento de fatura"),
    (_t("f2", -2300, "2026-10-10", None, descricao="Pagamento da fatura"), CONTA_CORRENTE, "pagamento de fatura"),
    (_t("i", -500, "2026-10-10", "03010000", descricao="Aplicação RDB"), CONTA_CORRENTE, "investimento"),
    (_t("c", -500, "2026-10-10", None, descricao="Dinheiro guardado na Caixinha"), CONTA_CORRENTE, "investimento"),
    (_t("sp", -500, "2026-10-10", "04020000"), CONTA_CORRENTE, "entre contas próprias"),
    (_t("sp2", -500, "2026-10-10", None) | {"category": "Same person transfer - PIX"}, CONTA_CORRENTE,
     "entre contas próprias"),
    (_pix("pp", -500, "2026-10-10", recebedor=CPF), CONTA_CORRENTE, "entre contas próprias"),
    (_t("pou", -20, "2026-10-10", "10000000"), CONTA_POUPANCA, "conta que não é corrente"),
])
def test_fica_de_fora(t, conta, motivo):
    assert _converter(t, conta) == ([], motivo)


def test_pix_para_outra_pessoa_e_gasto_com_a_mensagem():
    [g], motivo = _converter(_pix("x1", -50.0, "2026-10-20", mensagem="presente"))
    assert motivo is None
    assert (g.id_externo, g.data, g.valor, g.categoria, g.forma_pagamento) == (
        "pluggy:x1", date(2026, 10, 20), Decimal("50.00"), "transferência", "pix Nubank")
    assert g.descricao == "Transferência enviada pelo Pix · presente"


def test_compra_no_cartao_usa_a_categoria_mais_especifica():
    # Pluggy manda o gasto do cartão com valor positivo e tipo DEBIT: o sinal não importa, o tipo sim.
    [g], _ = _converter(_t("x2", 120, "2026-10-20", "19050001", descricao="Posto Sintético"), CARTAO)
    assert (g.valor, g.categoria, g.forma_pagamento) == (Decimal("120.00"), "combustível", "cartão de crédito Nubank")


def test_moeda_estrangeira_usa_o_valor_em_reais():
    [g], _ = _converter(_t("x3", 10, "2026-10-20", "09020000", amountInAccountCurrency=55.37), CARTAO)
    assert (g.valor, g.categoria) == (Decimal("55.37"), "assinaturas")


@pytest.mark.parametrize("codigo,categoria", [
    ("19050002", "transporte"), ("11020000", "alimentação"), ("09010000", "lazer"), ("07010001", "casa"),
    ("200300000", "saúde"), ("15010000", "outros"), ("05090004", "transferência"),
])
def test_categoria_pelo_prefixo_mais_longo(codigo, categoria):
    [g], _ = _converter(_t("pc", 10, "2026-10-20", codigo), CARTAO)
    assert g.categoria == categoria


def test_sem_categoria_conhecida_vai_para_outros():
    [g], _ = _converter(_t("x4", -15, "2026-10-20", None, descricao="Coisa"))
    assert (g.categoria, g.forma_pagamento) == ("outros", "débito Nubank")


def test_data_no_fuso_de_sao_paulo():
    # 01:30 UTC do dia 21 = 22:30 do dia 20 em São Paulo.
    t = _t("x5", -15, "2026-10-21") | {"date": "2026-10-21T01:30:00.000Z"}
    [g], _ = _converter(t)
    assert g.data == date(2026, 10, 20)


def test_descricao_com_cara_de_segredo_e_retida():
    [g], _ = _converter(_pix("x6", -1, "2026-10-20", mensagem="AKIAIOSFODNN7EXAMPLE"))
    assert g.descricao == pluggy.DESCRICAO_RETIDA


def test_parcela_lanca_as_futuras_com_o_numero_do_banco():
    gastos, _ = _converter(_parcela("x7", 89.9, "2026-10-10", 3, 10), CARTAO)
    assert [g.descricao for g in gastos[:2]] == ["Loja Sintética (03/10)", "Loja Sintética (04/10)"]
    assert len(gastos) == 8 and gastos[-1].descricao.endswith("(10/10)")
    assert [g.data for g in gastos[:3]] == [date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)]
    assert [g.real for g in gastos[:2]] == [True, False]
    chaves = {g.id_externo.rsplit(":", 1)[0] for g in gastos}
    assert len(chaves) == 1 and gastos[0].id_externo.endswith(":03")


def test_parcela_seguinte_tem_a_mesma_chave():
    a, _ = _converter(_parcela("y1", 89.9, "2026-10-10", 3, 10), CARTAO)
    b, _ = _converter(_parcela("y2", 89.9, "2026-11-10", 4, 10), CARTAO)
    assert b[0].id_externo == a[1].id_externo


def test_fim_do_mes_na_parcela():
    gastos, _ = _converter(_parcela("y3", 10, "2026-01-31", 1, 3, compra="2026-01-31T03:00:00.000Z"), CARTAO)
    assert [g.data for g in gastos] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


# ---------------- Sincronização ----------------


def test_primeira_sincronizacao_traz_12_meses_conferidos(bancos, url):
    api = ApiFalsa({"conta-cc": [_pix("a1", -50, "2026-10-20", "presente"), _t("a2", 3000, "2026-10-05", tipo="CREDIT"),
                                 _t("a3", -2300, "2026-10-10", "05100000")],
                    "conta-cartao": [_t("a4", 120, "2026-10-21", "10000000"), _parcela("a5", 89.9, "2026-10-10", 3, 10)]})
    r = _sincronizar(bancos, api)
    assert r.primeira and r.novos == 10 and r.fora == {"entrada": 1, "pagamento de fatura": 1}
    assert api.desdes() == {str(AGORA.date() - timedelta(days=365))}
    gastos = _gastos(url)
    assert all(g.conferido and g.origem == "pluggy" for g in gastos)
    with Session(create_engine(url)) as s:
        aud = s.scalars(select(Auditoria)).all()
        sinc = s.scalars(select(Sincronizacao)).all()
    assert len(aud) == 10 and {a.autor for a in aud} == {"worker:pluggy"} and {a.acao for a in aud} == {"criar"}
    assert [(x.worker, x.ok, x.novos, x.erro) for x in sinc] == [("pluggy", True, 10, None)]


def test_rodar_de_novo_nao_duplica_e_a_parcela_real_nao_repete(bancos, url):
    transacoes = {"conta-cartao": [_parcela("b1", 89.9, "2026-10-10", 3, 10)]}
    _sincronizar(bancos, ApiFalsa(transacoes))
    transacoes["conta-cartao"].append(_parcela("b2", 89.9, "2026-11-10", 4, 10))
    api = ApiFalsa(transacoes)
    r = _sincronizar(bancos, api, agora=AGORA + timedelta(days=16))
    assert (r.primeira, r.novos, r.ja_existiam) == (False, 0, 8)  # a 4/10 real e a projetada viram uma
    # Parado 16 dias: lê desde a última sincronização boa, com 1 dia de folga.
    assert api.desdes() == {str(AGORA.date() - timedelta(days=1))}
    gastos = _gastos(url)
    assert len(gastos) == 8
    assert [g.previsto for g in gastos[:3]] == [False, False, True]  # a 04/10 chegou: deixou de ser prevista


def test_rodada_seguinte_le_so_7_dias(bancos):
    _sincronizar(bancos, ApiFalsa({}))
    api = ApiFalsa({})
    _sincronizar(bancos, api, agora=AGORA + timedelta(hours=6))
    assert api.desdes() == {str(AGORA.date() - timedelta(days=7))}


def test_parcela_com_centavos_diferentes_nao_duplica(bancos, url):
    # R$ 100,00 em 3x: 33,34 + 33,33 + 33,33.
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("k1", 33.34, "2026-10-10", 1, 3, compra="2026-10-10T03:00:00.000Z")]}))
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("k2", 33.33, "2026-11-10", 2, 3, compra="2026-10-10T03:00:00.000Z")]}),
                 agora=AGORA + timedelta(days=16))
    assert len(_gastos(url)) == 3


def test_tres_compras_parceladas_no_mesmo_dia_e_loja_ficam_separadas(bancos, url):
    # Caso real do Nubank: três 12x no mesmo dia, mesma loja, valores diferentes.
    ts = [_parcela(f"r{i}", v, "2026-10-01", 1, 12, compra="2026-10-01T03:00:00.000Z") for i, v in enumerate((19.5, 80, 158))]
    _sincronizar(bancos, ApiFalsa({"conta-cartao": ts}))
    assert len(_gastos(url)) == 36


def test_parcela_real_acerta_data_e_valor_da_prevista(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("s1", 33.34, "2026-10-27", 1, 3, compra="2026-10-27T03:00:00.000Z")]}))
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("s2", 33.33, "2026-11-06", 2, 3, compra="2026-10-27T03:00:00.000Z")]}),
                 agora=AGORA + timedelta(days=12))
    segunda = [g for g in _gastos(url) if g.descricao.endswith("(02/03)")][0]
    assert (segunda.data, segunda.valor, segunda.previsto) == (date(2026, 11, 6), Decimal("33.33"), False)
    with Session(create_engine(url)) as s:
        [a] = s.scalars(select(Auditoria).where(Auditoria.acao == "confirmar")).all()
    assert a.dados == {"previsto": False, "data": "2026-11-06", "data_anterior": "2026-11-27",
                       "valor": "33.33", "valor_anterior": "33.34"}


def test_parcela_sem_data_da_compra_usa_a_data_menos_os_meses(bancos, url):
    t1 = _parcela("m1", 20, "2026-09-10", 1, 3) | {"creditCardMetadata": {"installmentNumber": 1, "totalInstallments": 3}}
    t2 = _parcela("m2", 20, "2026-10-10", 2, 3) | {"creditCardMetadata": {"installmentNumber": 2, "totalInstallments": 3}}
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [t1, t2]}))
    assert len(_gastos(url)) == 3


def test_conexao_refeita_com_ids_novos_vira_a_conferir(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cc": [_pix("n1", -50, "2026-10-20", "presente")]}))
    _sincronizar(bancos, ApiFalsa({"conta-cc": [_pix("n1-novo", -50, "2026-10-20", "presente")]}), agora=AGORA + timedelta(days=1))
    antigo, novo = _gastos(url)
    assert novo.duplicata_de == antigo.id and not novo.conferido


def test_parcela_prevista_que_nao_chega_e_desfeita_com_as_seguintes(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("o1", 30, "2026-10-10", 1, 4, compra="2026-10-10T03:00:00.000Z")]}))
    # 2026-11-10 + 40 dias = 2026-12-20: em 2026-12-21, a 02/04 não veio (compra estornada).
    r = _sincronizar(bancos, ApiFalsa({}), agora=datetime(2026, 12, 21, 6, 0, tzinfo=TZ))
    assert r.previstas_desfeitas == 3
    assert [(g.descricao[-7:], g.desfeito) for g in _gastos(url)] == [
        ("(01/04)", False), ("(02/04)", True), ("(03/04)", True), ("(04/04)", True)]
    with Session(create_engine(url)) as s:
        motivos = [a.dados.get("motivo") for a in s.scalars(select(Auditoria).where(Auditoria.acao == "desfazer"))]
    assert motivos == ["parcela prevista não chegou do banco"] * 3


def test_gasto_novo_depois_da_primeira_chega_a_conferir_e_aponta_o_manual(bancos, url):
    _sincronizar(bancos, ApiFalsa({}))
    with Session(create_engine(url)) as s, s.begin():
        s.add(Gasto(data=date(2026, 10, 25), valor=Decimal("120.00"), descricao="mercado", categoria="alimentação"))
    api = ApiFalsa({"conta-cartao": [_t("c1", 120, "2026-10-26", "10000000"), _t("c2", 30, "2026-10-26", "10000000"),
                                     _parcela("c3", 50, "2026-10-26", 1, 3, compra="2026-10-26T03:00:00.000Z")]})
    _sincronizar(bancos, api, agora=AGORA + timedelta(days=1))
    por_id = {g.id_externo: g for g in _gastos(url)}
    manual = por_id[None]
    assert not por_id["pluggy:c1"].conferido and por_id["pluggy:c1"].duplicata_de == manual.id
    assert not por_id["pluggy:c2"].conferido and por_id["pluggy:c2"].duplicata_de is None
    parcelas = sorted(k for k in por_id if k and k.startswith("pluggy-parcela:"))
    assert [por_id[k].conferido for k in parcelas] == [False, True, True]  # só a real pede conferência


def test_falha_de_login_fica_anotada(bancos, url):
    with pytest.raises(pluggy.ErroPluggy, match="401"):
        _sincronizar(bancos, ApiFalsa({}, status_auth=401))
    with Session(create_engine(url)) as s:
        [x] = s.scalars(select(Sincronizacao)).all()
    assert (x.ok, x.novos) == (False, 0) and "401 em /auth" in x.erro and "segredo-teste" not in x.erro


def test_conexao_caida_fica_anotada(bancos, url):
    with pytest.raises(pluggy.ErroPluggy, match="LOGIN_ERROR"):
        _sincronizar(bancos, ApiFalsa({}, status_item="LOGIN_ERROR"))


def test_sem_chaves_fica_anotado_sem_chamar_o_pluggy(bancos, url):
    api = ApiFalsa({})
    with pytest.raises(pluggy.ErroPluggy, match="PLUGGY_ITEM_IDS"):
        _sincronizar(bancos, api, pluggy_item_ids="")
    assert api.pedidos == []


def test_chave_vencida_entra_de_novo_uma_vez():
    api = ApiFalsa({})
    vezes = {"n": 0}

    def com_401(req):
        if req.url.path == "/categories" and vezes["n"] == 0:
            vezes["n"] += 1
            return httpx2.Response(401)
        return api(req)

    cliente = pluggy.ClientePluggy("id-teste", "segredo-teste", "https://api.pluggy.teste", httpx2.MockTransport(com_401))
    assert cliente.categorias() == CATEGORIAS
    assert [r.url.path for r in api.pedidos].count("/auth") == 2


def test_5xx_tenta_de_novo_e_depois_desiste():
    api = ApiFalsa({})
    falhas = {"n": 0}

    def com_504(req):
        if req.url.path == "/accounts" and falhas["n"] < falhas["limite"]:
            falhas["n"] += 1
            return httpx2.Response(504)
        return api(req)

    falhas["limite"] = 2
    cliente = pluggy.ClientePluggy("id-teste", "segredo-teste", "https://api.pluggy.teste", httpx2.MockTransport(com_504))
    cliente._dormir = lambda s: None
    assert len(cliente.contas("item-1")) == 3
    falhas.update(n=0, limite=99)
    with pytest.raises(pluggy.ErroPluggy, match="504 em /accounts"):
        cliente.contas("item-1")


def test_simular_nao_abre_o_banco():
    api = ApiFalsa({"conta-cc": [_pix("s1", -50, "2026-10-20")]})
    saida = pluggy.simular(_cliente(api), _cfg(), 30)
    assert [g["id_externo"] for g in saida["gastos"]] == ["pluggy:s1"] and saida["por_categoria"] == {"transferência": 1}


def test_proximo_horario():
    assert proximo_horario(datetime(2026, 10, 26, 5, 59, tzinfo=TZ)) == datetime(2026, 10, 26, 6, 0, tzinfo=TZ)
    assert proximo_horario(datetime(2026, 10, 26, 6, 0, tzinfo=TZ)) == datetime(2026, 10, 26, 12, 0, tzinfo=TZ)
    assert proximo_horario(datetime(2026, 10, 26, 18, 30, tzinfo=TZ)) == datetime(2026, 10, 27, 0, 0, tzinfo=TZ)


# ---------------- Ferramentas ----------------


async def _chamar(url, nome, **args):
    async with Client(criar_servidor_banco(Bancos.de_urls(url, url), TZ)) as c:
        return (await c.call_tool(nome, args)).data


async def test_registrar_gasto_igual_ao_do_banco_pergunta_antes(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_t("d1", 120, "2026-10-20", "10000000", descricao="Mercado X")]}))
    r = await _chamar(url, "registrar_gasto", valor="120", descricao="mercado", categoria="alimentação", data="2026-10-22")
    assert r["id"] is None and "Não registrei" in r["confirmacao"] and "É o mesmo gasto?" in r["confirmacao"]
    assert r["parecido"][0]["descricao"] == "Mercado X"
    assert len(_gastos(url)) == 1
    r = await _chamar(url, "registrar_gasto", valor="120", descricao="mercado", categoria="alimentação",
                      data="2026-10-22", mesmo_assim=True)
    assert r["id"] and r["confirmacao"].endswith("Desfazer?")
    # 4 dias de diferença: não é parecido.
    r = await _chamar(url, "registrar_gasto", valor="120", descricao="outro", categoria="lazer", data="2026-10-24")
    assert r["id"]


async def test_conferir_troca_a_categoria_e_as_parcelas_seguintes(bancos, url):
    _sincronizar(bancos, ApiFalsa({}))
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("e1", 50, "2026-10-26", 1, 3, compra="2026-10-26T03:00:00.000Z"),
                                                    _t("e2", 30, "2026-10-26", "10000000")]}), agora=AGORA + timedelta(days=1))
    a = await _chamar(url, "gastos_a_conferir")
    assert a["total"] == 2 and {g["categoria"] for g in a["gastos"]} == {"compras", "alimentação"}
    parcela = next(g for g in a["gastos"] if "(01/03)" in g["descricao"])
    outro = next(g for g in a["gastos"] if g["id"] != parcela["id"])
    r = await _chamar(url, "conferir_gastos", itens=[{"id": parcela["id"], "categoria": "Lazer"}, {"id": outro["id"]}])
    assert (r["conferidos"], r["categorias_trocadas"], r["parcelas_seguintes"]) == (2, 1, 2)
    assert "Desfazer?" not in r["confirmacao"]
    assert (await _chamar(url, "gastos_a_conferir"))["total"] == 0
    assert [g.categoria for g in _gastos(url) if g.id_externo.startswith("pluggy-parcela:")] == ["lazer"] * 3
    aud = await _chamar(url, "consultar_auditoria", acao="conferir")
    # Uma por parcela seguinte, com a categoria anterior, mais a da parcela e a do outro gasto.
    assert len(aud) == 4
    assert sorted(a["dados"].get("parcela_de", 0) for a in aud) == [0, 0, parcela["id"], parcela["id"]]
    assert {a["dados"]["anterior"] for a in aud if "anterior" in a["dados"]} == {"compras"}
    # Conferir de novo sem mudar nada não grava auditoria.
    r = await _chamar(url, "conferir_gastos", itens=[{"id": outro["id"]}])
    assert r["conferidos"] == 0 and len(await _chamar(url, "consultar_auditoria", acao="conferir")) == 4


async def test_conferir_recusa_gasto_manual(url):
    g = await _chamar(url, "registrar_gasto", valor="10", descricao="café", categoria="alimentação")
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="registrado à mão"):
        await _chamar(url, "conferir_gastos", itens=[{"id": g["id"], "categoria": "lazer"}])


async def test_parcela_prevista_nao_dispara_o_aviso_de_duplicata(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_parcela("q1", 89.9, "2026-10-10", 1, 3, compra="2026-10-10T03:00:00.000Z")]}))
    r = await _chamar(url, "registrar_gasto", valor="89.90", descricao="outra coisa", categoria="lazer", data="2026-11-10")
    assert r["id"]
    assert await _chamar(url, "conciliar_gastos", inicio="2026-11-01", fim="2026-11-30") == []


async def test_conferir_gasto_desfeito_falha(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_t("f1", 30, "2026-10-20", "10000000")]}))
    [g] = _gastos(url)
    await _chamar(url, "desfazer_registro", tipo="gasto", id=g.id)
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="Não achei gasto em vigor"):
        await _chamar(url, "conferir_gastos", itens=[{"id": g.id}])


async def test_gastos_a_conferir_mostra_o_manual_parecido(bancos, url):
    _sincronizar(bancos, ApiFalsa({}))
    with Session(create_engine(url)) as s, s.begin():
        s.add(Gasto(data=date(2026, 10, 25), valor=Decimal("120.00"), descricao="mercado", categoria="alimentação"))
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_t("g1", 120, "2026-10-26", "10000000")]}), agora=AGORA + timedelta(days=1))
    [item] = (await _chamar(url, "gastos_a_conferir"))["gastos"]
    assert item["parece_com"]["descricao"] == "mercado"


async def test_conciliar_ignora_desfeito(bancos, url):
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_t("h1", 120, "2026-10-20", "10000000")]}))
    a = await _chamar(url, "registrar_gasto", valor="120", descricao="mercado", categoria="alimentação",
                      data="2026-10-21", mesmo_assim=True)
    await _chamar(url, "registrar_gasto", valor="99", descricao="outro", categoria="lazer", data="2026-10-21")
    pares = await _chamar(url, "conciliar_gastos", inicio="2026-10-01", fim="2026-10-31")
    assert [(p["manual"]["id"], p["banco"]["valor"]) for p in pares] == [(a["id"], "120.00")]
    await _chamar(url, "desfazer_registro", tipo="gasto", id=a["id"])
    assert await _chamar(url, "conciliar_gastos", inicio="2026-10-01", fim="2026-10-31") == []


async def test_consultar_gastos_conta_os_a_conferir(bancos, url):
    _sincronizar(bancos, ApiFalsa({}))
    _sincronizar(bancos, ApiFalsa({"conta-cartao": [_t("i1", 30, "2026-10-26", "10000000")]}), agora=AGORA + timedelta(days=1))
    c = await _chamar(url, "consultar_gastos", inicio="2026-10-01", fim="2026-10-31")
    assert c["a_conferir"] == 1 and c["gastos"][0]["origem"] == "pluggy" and c["gastos"][0]["conferido"] is False


# ---------------- Aviso no contexto_inicial ----------------


def _rodada(url, quando: datetime, ok: bool):
    with Session(create_engine(url)) as s, s.begin():
        s.add(Sincronizacao(worker="pluggy", inicio=quando, fim=quando, ok=ok, novos=0, erro=None if ok else "x"))


@pytest.mark.parametrize("rodadas,aviso", [
    ([], None),  # worker não está em uso (instância da Nathalia)
    ([(timedelta(days=1), True)], None),
    ([(timedelta(days=3), True), (timedelta(hours=1), False)], "Pluggy sem sincronizar desde 23/10"),
    ([(timedelta(days=3), False)], "Pluggy nunca sincronizou"),
    ([(timedelta(hours=5), False)], None),  # falhou agora há pouco: espera os 2 dias
])
def test_aviso_pluggy(url, rodadas, aviso):
    for atras, ok in rodadas:
        _rodada(url, AGORA - atras, ok)
    with Session(create_engine(url)) as s:
        texto = vault._aviso_pluggy(s, AGORA)
    assert (texto is None) if aviso is None else texto.startswith(aviso)
