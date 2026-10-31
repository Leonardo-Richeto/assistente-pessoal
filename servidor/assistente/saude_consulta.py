"""Leitura dos dados de saúde para o chat (Ficha 15, PLANO 5b.3) e para o `resumo_periodo` (Ficha 16, PLANO 5.2).

Devolve totais por dia e a lista de treinos, nunca amostra crua. Rotas GPS, eletrocardiogramas e o bloco "Me" ficam
fora (Ficha 15, regra 2). Tudo pela conexão de leitura. Datas no fuso do dono.

Escolhas que mudam número (Ficha 15, regra 4):
- Soma do dia (passos, energia, distância): o relógio e o iPhone medem os mesmos passos; vale a fonte com o maior
  total do dia, para não contar duas vezes.
- Sono: a noite é a do dia em que o dono acordou (o intervalo que termina entre 12:00 da véspera e 12:00 do dia).
  Vale a fonte com mais horas dormidas na noite; intervalos sobrepostos dela não somam duas vezes.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos import SaudeAmostra, SaudeTreino

MAX_DIAS = 400  # período máximo por consulta: um ano de frequência cardíaca são ~100 mil amostras

Metrica = Literal["sono", "treinos", "passos", "energia_ativa", "distancia", "frequencia_cardiaca",
                  "frequencia_repouso", "variabilidade", "oxigenio", "vo2max"]

# nome: (tipo do app Saúde, agregação do dia, unidade devolvida)
METRICAS: dict[str, tuple[str, str, str]] = {
    "passos": ("HKQuantityTypeIdentifierStepCount", "soma", "passos"),
    "energia_ativa": ("HKQuantityTypeIdentifierActiveEnergyBurned", "soma", "kcal"),
    "distancia": ("HKQuantityTypeIdentifierDistanceWalkingRunning", "soma", "km"),
    "frequencia_cardiaca": ("HKQuantityTypeIdentifierHeartRate", "media", "bpm"),
    "frequencia_repouso": ("HKQuantityTypeIdentifierRestingHeartRate", "media", "bpm"),
    "variabilidade": ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "media", "ms"),
    "oxigenio": ("HKQuantityTypeIdentifierOxygenSaturation", "media", "%"),
    "vo2max": ("HKQuantityTypeIdentifierVO2Max", "ultimo", "mL/kg·min"),
}

# Unidade que veio -> fator para a unidade devolvida.
_CONVERSAO = {"kJ": 1 / 4.184, "mi": 1.609344, "m": 0.001, "km": 1.0, "Cal": 1.0, "kcal": 1.0}

SONO = "HKCategoryTypeIdentifierSleepAnalysis"
FASES = {
    "HKCategoryValueSleepAnalysisAsleepCore": "leve",
    "HKCategoryValueSleepAnalysisAsleepDeep": "profundo",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "sem_fase",
    "HKCategoryValueSleepAnalysisAsleep": "sem_fase",  # relógios e apps antigos, antes das fases
}
ACORDADO = "HKCategoryValueSleepAnalysisAwake"

DISTANCIAS = ("HKQuantityTypeIdentifierDistanceWalkingRunning", "HKQuantityTypeIdentifierDistanceCycling",
              "HKQuantityTypeIdentifierDistanceSwimming", "HKQuantityTypeIdentifierDistanceWheelchair",
              "HKQuantityTypeIdentifierDistanceDownhillSnowSports")

NOMES_TREINO = {
    "HKWorkoutActivityTypeTraditionalStrengthTraining": "musculação",
    "HKWorkoutActivityTypeFunctionalStrengthTraining": "treino funcional",
    "HKWorkoutActivityTypeCoreTraining": "core",
    "HKWorkoutActivityTypeHighIntensityIntervalTraining": "HIIT",
    "HKWorkoutActivityTypeWalking": "caminhada",
    "HKWorkoutActivityTypeRunning": "corrida",
    "HKWorkoutActivityTypeCycling": "bicicleta",
    "HKWorkoutActivityTypeStairClimbing": "escada",
    "HKWorkoutActivityTypeStairs": "escada",
    "HKWorkoutActivityTypeElliptical": "elíptico",
    "HKWorkoutActivityTypeSwimming": "natação",
    "HKWorkoutActivityTypeYoga": "ioga",
    "HKWorkoutActivityTypeSoccer": "futebol",
    "HKWorkoutActivityTypeDance": "dança",
    "HKWorkoutActivityTypeCooldown": "desaquecimento",
    "HKWorkoutActivityTypeOther": "outro",
}


def nome_treino(tipo: str) -> str:
    return NOMES_TREINO.get(tipo) or tipo.removeprefix("HKWorkoutActivityType")


def _utc(m: datetime) -> datetime:
    # O SQLite (testes) devolve sem fuso o que gravou em UTC; o Postgres devolve com fuso.
    return m.replace(tzinfo=timezone.utc) if m.tzinfo is None else m.astimezone(timezone.utc)


def _numero(v: float, casas: int = 1) -> float:
    return round(v, casas)


def _valor(metrica: str, valor: float, unidade: str | None) -> float:
    if metrica == "oxigenio" and valor <= 1:  # o app Saúde grava 0.97 com unidade "%"
        return valor * 100
    return valor * _CONVERSAO.get(unidade or "", 1.0)


def _janela(inicio: date, fim: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Meia-noite local do início e do dia seguinte ao fim, em UTC: as tabelas de saúde guardam UTC (o SQLite dos
    testes compara o texto, sem converter o fuso)."""
    def utc(d: date) -> datetime:
        return datetime.combine(d, datetime.min.time(), tz).astimezone(timezone.utc)
    return utc(inicio), utc(fim + timedelta(days=1))


# --- métricas por dia -----------------------------------------------------------------------------------------


def por_dia(s: Session, metrica: str, inicio: date, fim: date, tz: ZoneInfo) -> list[dict]:
    """Um item por dia com dado: soma (maior fonte), média com mínimo e máximo, ou o último valor do dia."""
    tipo, agregacao, _ = METRICAS[metrica]
    de, ate = _janela(inicio, fim, tz)
    linhas = s.execute(select(SaudeAmostra.inicio, SaudeAmostra.valor, SaudeAmostra.unidade, SaudeAmostra.origem).where(
        SaudeAmostra.tipo == tipo, SaudeAmostra.inicio >= de, SaudeAmostra.inicio < ate,
        SaudeAmostra.desfeito.is_(False), SaudeAmostra.valor.is_not(None))).all()
    dias: dict[date, list[tuple[datetime, float, str]]] = defaultdict(list)
    for inicio_amostra, valor, unidade, origem in linhas:
        momento = _utc(inicio_amostra).astimezone(tz)
        dias[momento.date()].append((momento, _valor(metrica, valor, unidade), origem))
    saida = []
    for dia in sorted(dias):
        itens = dias[dia]
        if agregacao == "soma":
            por_fonte: dict[str, float] = defaultdict(float)
            for _, v, origem in itens:
                por_fonte[origem] += v
            fonte, total = max(por_fonte.items(), key=lambda kv: kv[1])
            saida.append({"data": dia.isoformat(), "total": _numero(total, 0 if metrica == "passos" else 1),
                          "fonte": fonte})
        elif agregacao == "media":
            valores = [v for _, v, _ in itens]
            saida.append({"data": dia.isoformat(), "media": _numero(sum(valores) / len(valores)),
                          "minimo": _numero(min(valores)), "maximo": _numero(max(valores)), "amostras": len(valores)})
        else:
            momento, v, _ = max(itens, key=lambda i: i[0])
            saida.append({"data": dia.isoformat(), "valor": _numero(v)})
    return saida


# --- sono -----------------------------------------------------------------------------------------------------


def _noite(fim_intervalo: datetime, tz: ZoneInfo) -> date:
    """O dia em que acordou: o intervalo que termina entre 12:00 da véspera e 12:00 do dia é desta noite."""
    return (fim_intervalo.astimezone(tz) + timedelta(hours=12)).date()


def _uniao_segundos(intervalos: list[tuple[datetime, datetime]]) -> float:
    total, fim_aberto, inicio_aberto = 0.0, None, None
    for a, b in sorted(intervalos):
        if fim_aberto is None or a > fim_aberto:
            if fim_aberto is not None:
                total += (fim_aberto - inicio_aberto).total_seconds()
            inicio_aberto, fim_aberto = a, b
        else:
            fim_aberto = max(fim_aberto, b)
    if fim_aberto is not None:
        total += (fim_aberto - inicio_aberto).total_seconds()
    return total


def noites(s: Session, inicio: date, fim: date, tz: ZoneInfo) -> list[dict]:
    """Uma noite por dia em que acordou, com horas dormidas, horas por fase e horas acordado no meio."""
    # A noite vai do 12:00 local da véspera ao 12:00 local do dia (certo também nos dias de troca de horário).
    de = datetime.combine(inicio - timedelta(days=1), datetime.min.time().replace(hour=12), tz).astimezone(timezone.utc)
    ate = datetime.combine(fim, datetime.min.time().replace(hour=12), tz).astimezone(timezone.utc)
    linhas = s.execute(select(SaudeAmostra.inicio, SaudeAmostra.fim, SaudeAmostra.valor_texto, SaudeAmostra.origem).where(
        SaudeAmostra.tipo == SONO, SaudeAmostra.fim >= de, SaudeAmostra.fim < ate,
        # Limite pelo início também, para o índice (tipo, inicio) restringir a faixa: nenhum trecho dura 36 h.
        SaudeAmostra.inicio >= de - timedelta(hours=36), SaudeAmostra.inicio < ate,
        SaudeAmostra.desfeito.is_(False))).all()
    grupos: dict[tuple[date, str], dict] = {}
    for a, b, valor, origem in linhas:
        a, b = _utc(a), _utc(b)
        if b <= a:
            continue
        g = grupos.setdefault((_noite(b, tz), origem), {"dormindo": [], "fases": defaultdict(list), "acordado": []})
        if valor in FASES:
            g["dormindo"].append((a, b))
            g["fases"][FASES[valor]].append((a, b))
        elif valor == ACORDADO:
            g["acordado"].append((a, b))
    melhores: dict[date, tuple[float, str, dict]] = {}
    for (noite, origem), g in grupos.items():
        dormido = _uniao_segundos(g["dormindo"])
        if dormido and (noite not in melhores or dormido > melhores[noite][0]):
            melhores[noite] = (dormido, origem, g)
    saida = []
    for noite in sorted(melhores):
        if not inicio <= noite <= fim:
            continue
        dormido, origem, g = melhores[noite]
        fases = {f: _uniao_segundos(v) for f, v in g["fases"].items()}
        if len(fases) > 1:  # com fases, o "sem fase" repete o mesmo trecho com outro rótulo: não conta
            fases.pop("sem_fase", None)
        saida.append({"noite": noite.isoformat(), "horas": _numero(dormido / 3600, 2),
                      "fases_horas": {f: _numero(v / 3600, 2) for f, v in sorted(fases.items())},
                      "acordado_horas": _numero(_uniao_segundos(g["acordado"]) / 3600, 2), "fonte": origem})
    return saida


# --- treinos --------------------------------------------------------------------------------------------------


def _estatistica(t: SaudeTreino, tipos: tuple[str, ...], campo: str, somar: bool = True) -> float | None:
    """Soma (ou, com somar=False, a primeira) das estatísticas do treino com o tipo exato."""
    total = None
    for e in t.estatisticas or []:
        if (e.get("type") or "") in tipos:
            try:
                v = float(e.get(campo))
            except (TypeError, ValueError):
                continue
            v *= _CONVERSAO.get(e.get("unit") or "", 1.0)
            if not somar:
                return v
            total = v if total is None else total + v
    return total


def _minutos(t: SaudeTreino) -> float | None:
    if t.duracao is None:
        return None
    return t.duracao * {"min": 1, "s": 1 / 60, "hr": 60, "h": 60}.get(t.unidade_duracao or "min", 1)


def treinos(s: Session, inicio: date, fim: date, tz: ZoneInfo) -> list[dict]:
    """Os treinos do período em ordem, com tipo em português, duração, energia, distância e frequência média."""
    de, ate = _janela(inicio, fim, tz)
    lista = s.scalars(select(SaudeTreino).where(SaudeTreino.inicio >= de, SaudeTreino.inicio < ate,
                                                SaudeTreino.desfeito.is_(False)).order_by(SaudeTreino.inicio)).all()
    saida = []
    for t in lista:
        quando = _utc(t.inicio).astimezone(tz)
        minutos, energia = _minutos(t), _estatistica(t, ("HKQuantityTypeIdentifierActiveEnergyBurned",), "sum")
        distancia = _estatistica(t, DISTANCIAS, "sum")
        fc = _estatistica(t, ("HKQuantityTypeIdentifierHeartRate",), "average", somar=False)
        saida.append({"data": quando.date().isoformat(), "hora": f"{quando:%H:%M}", "tipo": nome_treino(t.tipo),
                      "duracao_min": None if minutos is None else _numero(minutos, 0),
                      "energia_kcal": None if energia is None else _numero(energia, 0),
                      "distancia_km": None if distancia is None else _numero(distancia, 2),
                      "frequencia_media": None if fc is None else _numero(fc, 0), "fonte": t.origem})
    return saida


def ultimo_treino(s: Session, tz: ZoneInfo) -> dict | None:
    t = s.scalars(select(SaudeTreino).where(SaudeTreino.desfeito.is_(False)).order_by(SaudeTreino.inicio.desc())
                  .limit(1)).first()
    if t is None:
        return None
    return {"data": _utc(t.inicio).astimezone(tz).date(), "tipo": nome_treino(t.tipo)}


# --- resumo ---------------------------------------------------------------------------------------------------


def _media(valores: list[float], casas: int = 1) -> float | None:
    return _numero(sum(valores) / len(valores), casas) if valores else None


def resumo(s: Session, inicio: date, fim: date, tz: ZoneInfo) -> dict:
    """Sono, treinos, passos, frequência em repouso e VO2máx do período (Ficha 15, regra 3; sem os anéis)."""
    lista_noites = noites(s, inicio, fim, tz)
    fases: dict[str, list[float]] = defaultdict(list)
    for n in lista_noites:
        for f, h in n["fases_horas"].items():
            fases[f].append(h)
    lista_treinos = treinos(s, inicio, fim, tz)
    por_tipo: dict[str, int] = defaultdict(int)
    for t in lista_treinos:
        por_tipo[t["tipo"]] += 1
    passos = [d["total"] for d in por_dia(s, "passos", inicio, fim, tz)]
    repouso = [d["media"] for d in por_dia(s, "frequencia_repouso", inicio, fim, tz)]
    _, ate = _janela(inicio, fim, tz)
    vo2 = s.execute(select(SaudeAmostra.inicio, SaudeAmostra.valor).where(
        SaudeAmostra.tipo == METRICAS["vo2max"][0], SaudeAmostra.inicio < ate, SaudeAmostra.desfeito.is_(False),
        SaudeAmostra.valor.is_not(None)).order_by(SaudeAmostra.inicio.desc()).limit(1)).first()
    return {
        "sono": None if not lista_noites else {
            "noites": len(lista_noites), "media_horas": _media([n["horas"] for n in lista_noites], 2),
            "menor_horas": min(n["horas"] for n in lista_noites), "maior_horas": max(n["horas"] for n in lista_noites),
            # Média só das noites que têm a fase (relógio antigo não separa fases).
            "fases_media_horas": {f: _media(v, 2) for f, v in sorted(fases.items())}},
        "treinos": {
            "quantidade": len(lista_treinos), "por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1])),
            "duracao_total_min": _numero(sum(t["duracao_min"] or 0 for t in lista_treinos), 0),
            "energia_total_kcal": _numero(sum(t["energia_kcal"] or 0 for t in lista_treinos), 0)},
        "passos": None if not passos else {"media_por_dia": _numero(sum(passos) / len(passos), 0), "dias": len(passos),
                                           "total": _numero(sum(passos), 0)},
        "frequencia_repouso": None if not repouso else {"media": _media(repouso), "dias": len(repouso)},
        # O último medido até o fim do período, mesmo antes dele: o relógio só mede em caminhada ou corrida na rua.
        "vo2max": None if not vo2 else {"ultimo": _numero(vo2.valor),
                                        "data": _utc(vo2.inicio).astimezone(tz).date().isoformat()},
    }


def tem_dados(s: Session) -> bool:
    return s.scalar(select(SaudeAmostra.id).limit(1)) is not None or \
        s.scalar(select(SaudeTreino.id).limit(1)) is not None
