"""Consultas da saúde (Ficha 15) e resumo do período (Ficha 16), com o cliente MCP em memória e SQLite.

Os dados são sintéticos, gravados direto nas tabelas da Ficha 14 (o importador tem os testes dele em test_saude.py).
"""

import hashlib
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from assistente.banco import criar_servidor_banco
from assistente.db import Bancos
from assistente.modelos import Atividade, Base, Gasto, Ponto, SaudeAmostra, SaudeTreino

TZ = ZoneInfo("America/Sao_Paulo")
SONO = "HKCategoryTypeIdentifierSleepAnalysis"
PASSOS = "HKQuantityTypeIdentifierStepCount"
CORE, DEEP, REM = ("HKCategoryValueSleepAnalysisAsleepCore", "HKCategoryValueSleepAnalysisAsleepDeep",
                   "HKCategoryValueSleepAnalysisAsleepREM")


@pytest.fixture
def url(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'teste.db'}"
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return url


@pytest.fixture
def servidor(url):
    return criar_servidor_banco(Bancos.de_urls(url, url), TZ)


async def chamar(servidor, nome, **args):
    async with Client(servidor) as c:
        return (await c.call_tool(nome, args)).data


def local(dia: date, hora: str) -> datetime:
    """Hora de São Paulo em UTC, como o importador grava a saúde."""
    return sp(dia, hora).astimezone(timezone.utc)


def sp(dia: date, hora: str) -> datetime:
    """Hora de São Paulo com o fuso, como registrar_ponto e registrar_atividade gravam."""
    h, m = (int(x) for x in hora.split(":"))
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=TZ)


_n = [0]


def _chave() -> str:
    _n[0] += 1
    return hashlib.sha256(str(_n[0]).encode()).hexdigest()


def amostra(tipo, inicio, fim=None, valor=None, texto=None, origem="Apple Watch", unidade=None) -> SaudeAmostra:
    return SaudeAmostra(chave=_chave(), tipo=tipo, inicio=inicio, fim=fim or inicio, valor=valor, valor_texto=texto,
                        origem=origem, unidade=unidade)


def treino(tipo, inicio, minutos, energia=None, distancia=None, fc=None) -> SaudeTreino:
    est = []
    if energia is not None:
        est.append({"type": "HKQuantityTypeIdentifierActiveEnergyBurned", "sum": str(energia), "unit": "Cal"})
    if distancia is not None:
        est.append({"type": "HKQuantityTypeIdentifierDistanceWalkingRunning", "sum": str(distancia), "unit": "km"})
    if fc is not None:
        est.append({"type": "HKQuantityTypeIdentifierHeartRate", "average": str(fc), "unit": "count/min"})
    return SaudeTreino(chave=_chave(), tipo=tipo, inicio=inicio, fim=inicio + timedelta(minutes=minutos),
                       duracao=float(minutos), unidade_duracao="min", origem="Apple Watch", estatisticas=est,
                       eventos=[], zonas=[], amostras=[])


def gravar(url, *linhas) -> None:
    with Session(create_engine(url)) as s, s.begin():
        s.add_all(linhas)


D = date(2026, 10, 27)  # terça


async def test_sono_por_noite_com_fases_e_fonte_maior(servidor, url):
    vespera = D - timedelta(days=1)
    gravar(url,
           # Relógio: 23:00–02:00 leve, 02:00–03:00 profundo, 03:00–03:30 acordado, 03:30–06:30 REM = 7 h dormidas.
           amostra(SONO, local(vespera, "23:00"), local(D, "02:00"), texto=CORE),
           amostra(SONO, local(D, "02:00"), local(D, "03:00"), texto=DEEP),
           amostra(SONO, local(D, "03:00"), local(D, "03:30"), texto="HKCategoryValueSleepAnalysisAwake"),
           amostra(SONO, local(D, "03:30"), local(D, "06:30"), texto=REM),
           # Trecho repetido do relógio (sobreposto): não soma de novo.
           amostra(SONO, local(D, "01:00"), local(D, "01:30"), texto=CORE),
           # iPhone: só "na cama" e um sono curto: perde para o relógio.
           amostra(SONO, local(vespera, "22:30"), local(D, "07:00"), texto="HKCategoryValueSleepAnalysisInBed",
                   origem="iPhone"),
           amostra(SONO, local(D, "00:00"), local(D, "05:00"), texto="HKCategoryValueSleepAnalysisAsleep",
                   origem="iPhone"))
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="sono")
    (noite,) = r["itens"]
    assert (noite["noite"], noite["horas"], noite["fonte"]) == ("2026-10-27", 7.0, "Apple Watch")
    assert noite["fases_horas"] == {"leve": 3.0, "profundo": 1.0, "rem": 3.0}  # o trecho repetido não soma
    assert noite["acordado_horas"] == 0.5
    assert r["unidade"] == "horas"


async def test_passos_vale_a_fonte_maior_do_dia(servidor, url):
    gravar(url,
           amostra(PASSOS, local(D, "08:00"), valor=3000, unidade="count"),
           amostra(PASSOS, local(D, "12:00"), valor=2000, unidade="count"),
           amostra(PASSOS, local(D, "09:00"), valor=4000, unidade="count", origem="iPhone"),
           amostra(PASSOS, local(D, "23:30"), valor=100, unidade="count", origem="iPhone"))
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="passos")
    assert r["itens"] == [{"data": "2026-10-27", "total": 5000, "fonte": "Apple Watch"}]


async def test_dia_no_fuso_de_sao_paulo(servidor, url):
    # 23:30 de São Paulo já é dia seguinte em UTC: conta no dia local.
    gravar(url, amostra(PASSOS, local(D, "23:30"), valor=10, unidade="count"))
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="passos")
    assert [i["data"] for i in r["itens"]] == ["2026-10-27"]


async def test_media_do_dia_e_oxigenio_em_porcentagem(servidor, url):
    fc = "HKQuantityTypeIdentifierHeartRate"
    gravar(url, amostra(fc, local(D, "08:00"), valor=60, unidade="count/min"),
           amostra(fc, local(D, "09:00"), valor=80, unidade="count/min"),
           amostra("HKQuantityTypeIdentifierOxygenSaturation", local(D, "03:00"), valor=0.97, unidade="%"))
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="frequencia_cardiaca")
    assert r["itens"] == [{"data": "2026-10-27", "media": 70.0, "minimo": 60.0, "maximo": 80.0, "amostras": 2}]
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="oxigenio")
    assert r["itens"][0]["media"] == 97.0


async def test_treinos_em_portugues_com_estatisticas(servidor, url):
    gravar(url,
           treino("HKWorkoutActivityTypeTraditionalStrengthTraining", local(D, "18:00"), 45, energia=300, fc=120),
           treino("HKWorkoutActivityTypeWalking", local(D, "07:00"), 30, energia=120, distancia=2.5),
           treino("HKWorkoutActivityTypeNovidade", local(D, "20:00"), 10))
    r = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="treinos")
    assert [(t["hora"], t["tipo"]) for t in r["itens"]] == [("07:00", "caminhada"), ("18:00", "musculação"),
                                                             ("20:00", "Novidade")]
    caminhada, musculacao, _ = r["itens"]
    assert (caminhada["duracao_min"], caminhada["energia_kcal"], caminhada["distancia_km"]) == (30, 120, 2.5)
    assert (musculacao["frequencia_media"], musculacao["distancia_km"]) == (120, None)


async def test_resumo_saude(servidor, url):
    gravar(url,
           amostra(SONO, local(D, "00:00"), local(D, "07:00"), texto=CORE),
           amostra(SONO, local(D + timedelta(days=1), "01:00"), local(D + timedelta(days=1), "06:00"), texto=CORE),
           amostra(PASSOS, local(D, "10:00"), valor=8000, unidade="count"),
           amostra(PASSOS, local(D + timedelta(days=1), "10:00"), valor=4000, unidade="count"),
           amostra("HKQuantityTypeIdentifierRestingHeartRate", local(D, "10:00"), valor=58, unidade="count/min"),
           amostra("HKQuantityTypeIdentifierVO2Max", local(D, "10:00"), valor=40.1, unidade="mL/min·kg"),
           amostra("HKQuantityTypeIdentifierVO2Max", local(D + timedelta(days=1), "10:00"), valor=41.3,
                   unidade="mL/min·kg"),
           treino("HKWorkoutActivityTypeTraditionalStrengthTraining", local(D, "18:00"), 45, energia=300),
           treino("HKWorkoutActivityTypeTraditionalStrengthTraining", local(D + timedelta(days=1), "18:00"), 50,
                  energia=320))
    r = await chamar(servidor, "resumo_saude", inicio=D.isoformat(), fim=(D + timedelta(days=1)).isoformat())
    assert r["sono"] == {"noites": 2, "media_horas": 6.0, "menor_horas": 5.0, "maior_horas": 7.0,
                         "fases_media_horas": {"leve": 6.0}}
    assert r["treinos"] == {"quantidade": 2, "por_tipo": {"musculação": 2}, "duracao_total_min": 95,
                            "energia_total_kcal": 620}
    assert r["passos"] == {"media_por_dia": 6000, "dias": 2, "total": 12000}
    assert r["frequencia_repouso"] == {"media": 58.0, "dias": 1}
    assert r["vo2max"] == {"ultimo": 41.3, "data": "2026-10-28"}
    assert "aneis" not in r and "rotas" not in str(r)  # sem anéis (Leonardo, 2026-10-31) e sem rota


async def test_resumo_saude_sem_dados(servidor):
    r = await chamar(servidor, "resumo_saude", inicio=D.isoformat(), fim=D.isoformat())
    assert r["sono"] is None and r["passos"] is None and r["treinos"]["quantidade"] == 0


@pytest.mark.parametrize("inicio, fim, motivo", [
    ("2026-10-27", "2026-10-26", "anterior"),
    ("2025-01-01", "2026-10-27", "longo demais"),
])
async def test_periodo_invalido(servidor, inicio, fim, motivo):
    for ferramenta, extra in (("consultar_saude", {"metrica": "passos"}), ("resumo_saude", {}),
                              ("resumo_periodo", {})):
        with pytest.raises(ToolError, match=motivo):
            await chamar(servidor, ferramenta, inicio=inicio, fim=fim, **extra)


async def test_resumo_periodo(servidor, url):
    hoje = datetime.now(TZ).date()
    inicio, fim = hoje - timedelta(days=10), hoje - timedelta(days=6)
    gravar(url,
           Gasto(data=inicio, valor=Decimal("50.00"), descricao="mercado", categoria="mercado"),
           Gasto(data=fim, valor=Decimal("30.50"), descricao="padaria", categoria="padaria", conferido=False),
           Gasto(data=fim, valor=Decimal("99.00"), descricao="desfeito", categoria="mercado", desfeito=True),
           Gasto(data=hoje, valor=Decimal("10.00"), descricao="fora do período", categoria="mercado"),
           Ponto(momento=sp(inicio, "09:00"), tipo="entrada"), Ponto(momento=sp(inicio, "17:00"), tipo="saida"),
           Ponto(momento=sp(hoje - timedelta(days=2), "09:00"), tipo="entrada"),
           Atividade(momento=sp(fim, "20:00"), descricao="estudei", tags="estudo,python"),
           Atividade(momento=sp(fim, "21:00"), descricao="li", tags="leitura"),
           amostra(SONO, local(fim, "00:00"), local(fim, "07:00"), texto=CORE),
           amostra(PASSOS, local(fim, "10:00"), valor=9000, unidade="count"),
           treino("HKWorkoutActivityTypeRunning", local(hoje - timedelta(days=4), "07:00"), 30))
    r = await chamar(servidor, "resumo_periodo", inicio=inicio.isoformat(), fim=fim.isoformat())
    assert r["gastos"] == {"total": "80.50", "quantidade": 2, "por_categoria": {"mercado": "50.00", "padaria": "30.50"},
                           "a_conferir": 1}
    assert r["ponto"] == {"total_horas": 8.0, "dias_trabalhados": 1}
    assert r["diario"] == {"registros": 2, "por_tag": {"estudo": 1, "python": 1, "leitura": 1}}
    assert r["saude"] == {"sono_media_horas": 7.0, "noites": 1, "treinos": 0, "passos_media_por_dia": 9000}
    # Contado até hoje: o treino é de depois do período, há 4 dias.
    assert r["dias_desde_o_ultimo"] == {
        "treino": {"data": (hoje - timedelta(days=4)).isoformat(), "dias": 4, "tipo": "corrida"},
        "ponto": {"data": (hoje - timedelta(days=2)).isoformat(), "dias": 2},
        "registro_do_diario": {"data": fim.isoformat(), "dias": 6},
    }


async def test_resumo_periodo_sem_saude_nem_registros(servidor):
    r = await chamar(servidor, "resumo_periodo", inicio=D.isoformat(), fim=D.isoformat())
    assert r["saude"] is None
    assert r["dias_desde_o_ultimo"] == {"treino": None, "ponto": None, "registro_do_diario": None}
    assert r["gastos"]["total"] == "0"


async def test_fc_do_treino_nao_soma_outras_estatisticas(servidor, url):
    t = treino("HKWorkoutActivityTypeRunning", local(D, "07:00"), 30, fc=150)
    t.estatisticas = t.estatisticas + [
        {"type": "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute", "average": "20", "unit": "count/min"},
        {"type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "average": "40", "unit": "ms"},
        {"type": "HKQuantityTypeIdentifierDistanceCycling", "sum": "1.5", "unit": "km"}]
    gravar(url, t)
    (item,) = (await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="treinos"))["itens"]
    assert (item["frequencia_media"], item["distancia_km"]) == (150, 1.5)


async def test_fase_repetida_com_outro_rotulo_nao_soma(servidor, url):
    gravar(url,
           amostra(SONO, local(D, "00:00"), local(D, "06:00"), texto=CORE),
           amostra(SONO, local(D, "00:00"), local(D, "06:00"), texto="HKCategoryValueSleepAnalysisAsleepUnspecified"),
           amostra(SONO, local(D, "01:00"), local(D, "02:00"), texto=CORE))  # dentro do trecho leve: não soma
    (noite,) = (await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="sono"))["itens"]
    assert (noite["horas"], noite["fases_horas"]) == (6.0, {"leve": 6.0})


async def test_sono_so_sem_fase_conta(servidor, url):
    # Relógio antigo: só "dormindo", sem fases. Aí o "sem fase" é a noite toda.
    gravar(url, amostra(SONO, local(D, "00:00"), local(D, "06:00"), texto="HKCategoryValueSleepAnalysisAsleep"))
    (noite,) = (await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="sono"))["itens"]
    assert noite["fases_horas"] == {"sem_fase": 6.0}


async def test_sono_no_dia_da_troca_de_horario(servidor, url):
    # 2017-10-15: o relógio de São Paulo pulou de 00:00 para 01:00 (horário de verão).
    troca = date(2017, 10, 15)
    gravar(url, amostra(SONO, local(troca - timedelta(days=1), "23:00"), local(troca, "11:30"), texto=CORE))
    (noite,) = (await chamar(servidor, "consultar_saude", inicio=troca.isoformat(), fim=troca.isoformat(),
                             metrica="sono"))["itens"]
    assert (noite["noite"], noite["horas"]) == ("2017-10-15", 11.5)  # 23:00 a 11:30 com uma hora a menos


async def test_desfeito_nao_conta(servidor, url):
    a = amostra(PASSOS, local(D, "08:00"), valor=3000, unidade="count")
    a.desfeito = True
    t = treino("HKWorkoutActivityTypeRunning", local(D, "07:00"), 30)
    t.desfeito = True
    gravar(url, a, t)
    r = await chamar(servidor, "resumo_saude", inicio=D.isoformat(), fim=D.isoformat())
    assert r["passos"] is None and r["treinos"]["quantidade"] == 0


async def test_unidades_kj_e_milhas(servidor, url):
    gravar(url,
           amostra("HKQuantityTypeIdentifierActiveEnergyBurned", local(D, "08:00"), valor=418.4, unidade="kJ"),
           amostra("HKQuantityTypeIdentifierDistanceWalkingRunning", local(D, "08:00"), valor=1.0, unidade="mi"))
    energia = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="energia_ativa")
    distancia = await chamar(servidor, "consultar_saude", inicio=D.isoformat(), fim=D.isoformat(), metrica="distancia")
    assert energia["itens"][0]["total"] == 100.0 and energia["unidade"] == "kcal"
    assert distancia["itens"][0]["total"] == 1.6 and distancia["unidade"] == "km"


async def test_vo2max_vem_da_ultima_medicao_ate_o_fim(servidor, url):
    gravar(url,
           amostra("HKQuantityTypeIdentifierVO2Max", local(D - timedelta(days=20), "10:00"), valor=39.5),
           amostra("HKQuantityTypeIdentifierVO2Max", local(D + timedelta(days=5), "10:00"), valor=45.0))  # depois
    r = await chamar(servidor, "resumo_saude", inicio=D.isoformat(), fim=D.isoformat())
    assert r["vo2max"] == {"ultimo": 39.5, "data": (D - timedelta(days=20)).isoformat()}


async def test_dias_desde_com_registro_de_madrugada(servidor, url):
    # 01:30 local ainda é o dia local (em UTC já seria 04:30, mas no SQLite a hora volta sem fuso).
    hoje = datetime.now(TZ).date()
    gravar(url, Atividade(momento=sp(hoje - timedelta(days=3), "01:30"), descricao="madrugada"))
    r = await chamar(servidor, "resumo_periodo", inicio=hoje.isoformat(), fim=hoje.isoformat())
    assert r["dias_desde_o_ultimo"]["registro_do_diario"] == {"data": (hoje - timedelta(days=3)).isoformat(), "dias": 3}
