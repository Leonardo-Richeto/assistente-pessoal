"""Saúde do Apple Watch (Ficha 14): importação do export.zip e pasta de entrada, em SQLite.

O export é SINTÉTICO (nunca dado real no repo), montado com os mesmos elementos do export real calibrado em
2026-10-31: amostras com metadados, sono, variabilidade com batidas, treino com estatísticas, eventos, zonas, rota e
amostra de dentro, anéis, Correlation, "Me", rotas .gpx, eletrocardiograma com vírgula decimal e export_cda.xml.
Os GRANTs no Postgres estão em test_saude_pg.py.
"""

import json
import os
import subprocess
import sys
import time
import tracemalloc
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from assistente import saude
from assistente.modelos import (Auditoria, SaudeAmostra, SaudeAnel, SaudeEcg, SaudeImportacao, SaudeRota,
                                SaudeTreino)
from test_registro import SERVIDOR, _alembic, url  # noqa: F401 (fixture)

DTD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
]>
"""
RELOGIO = "&lt;&lt;HKDevice: 0x{end}&gt;, name:Apple Watch, model:Watch, hardware:Watch6,2&gt;"


def xml(amostras: str = "", endereco: str = "283a3c1e0", fuso: str = "-0300", anel_energia: str = "450",
        extra: str = "") -> str:
    d = lambda h: f"2026-10-30 {h} {fuso}" if fuso == "-0300" else f"2026-10-30 {_outro_fuso(h)} {fuso}"  # noqa: E731
    disp = RELOGIO.format(end=endereco)
    return DTD + f"""<HealthData locale="pt_BR">
 <ExportDate value="2026-10-31 07:05:00 -0300"/>
 <Me HKCharacteristicTypeIdentifierDateOfBirth="1990-01-01" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch de Teste" sourceVersion="10.0" device="{disp}" unit="count/min" creationDate="{d('07:01:00')}" startDate="{d('07:00:00')}" endDate="{d('07:00:00')}" value="72">
  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="1"/>
 </Record>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch de Teste" sourceVersion="10.0" startDate="{d('01:00:00')}" endDate="{d('02:00:00')}" value="HKCategoryValueSleepAnalysisAsleepCore"/>
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Apple Watch de Teste" unit="ms" startDate="{d('03:00:00')}" endDate="{d('03:01:00')}" value="41.5">
  <HeartRateVariabilityMetadataList>
   <InstantaneousBeatsPerMinute bpm="60" time="3:00:01,00 AM"/>
   <InstantaneousBeatsPerMinute bpm="62" time="3:00:02,00 AM"/>
  </HeartRateVariabilityMetadataList>
 </Record>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="sem data" endDate="{d('08:00:00')}" value="10"/>
 {amostras}
 <Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="Medidor" startDate="{d('09:00:00')}" endDate="{d('09:00:00')}">
  <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Medidor" unit="mmHg" startDate="{d('09:00:00')}" endDate="{d('09:00:00')}" value="120"/>
 </Correlation>
 <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining" duration="45.5" durationUnit="min" sourceName="Apple Watch de Teste" device="{disp}" startDate="{d('18:00:00')}" endDate="{d('18:45:30')}">
  <MetadataEntry key="HKIndoorWorkout" value="1"/>
  <WorkoutEvent type="HKWorkoutEventTypeSegment" date="{d('18:00:00')}" duration="10" durationUnit="min"/>
  <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" startDate="{d('18:00:00')}" endDate="{d('18:45:30')}" sum="300" unit="Cal"/>
  <WorkoutZoneGroup type="HKQuantityTypeIdentifierHeartRate" source="Apple Watch de Teste" unit="count/min">
   <WorkoutZone maximum="120" duration="5" durationUnit="min"/>
  </WorkoutZoneGroup>
  <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch de Teste" unit="count/min" startDate="{d('18:10:00')}" endDate="{d('18:10:00')}" value="130"/>
  <WorkoutRoute sourceName="Apple Watch de Teste" startDate="{d('18:00:00')}" endDate="{d('18:45:30')}">
   <FileReference path="/workout-routes/route_2026-10-30_6.00pm.gpx"/>
  </WorkoutRoute>
  <Novidade x="1"/>
 </Workout>
 <ActivitySummary dateComponents="2026-10-30" activeEnergyBurned="{anel_energia}" activeEnergyBurnedGoal="500" activeEnergyBurnedUnit="Cal" appleExerciseTime="30" appleStandHours="10"/>
 <Audiogram sourceName="Teste"/>
 {extra}
</HealthData>
"""


def _outro_fuso(hora: str) -> str:
    """A mesma hora de -0300 escrita em +0000 (export feito com o iPhone em outro fuso)."""
    h, m, s = (int(x) for x in hora.split(":"))
    return f"{(h + 3) % 24:02d}:{m:02d}:{s:02d}"


GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">
 <metadata><time>{gerado}</time></metadata>
 <trk><name>Route</name><trkseg>
  <trkpt lon="-46.5" lat="-23.6"><ele>760.5</ele><time>2026-10-30T21:00:00Z</time><extensions><speed>1.2</speed><course>90.0</course><hAcc>1.5</hAcc><vAcc>1.0</vAcc></extensions></trkpt>
  <trkpt lon="-46.6" lat="-23.7"><ele>761.0</ele><time>2026-10-30T21:00:05Z</time><extensions><speed>1.3</speed><course>91.0</course><hAcc>1.4</hAcc><vAcc>1.1</vAcc></extensions></trkpt>
 </trkseg></trk>
</gpx>
"""

ECG = """﻿Nome,Pessoa de Teste
Nascimento,"1 de jan. de 1990"
Data do Registro,2026-10-30 10:20:30 -0300
Classificação,Ritmo Sinusal
Sintomas,
Taxa de Amostragem,512 hertz


Sensor,Sensor I
Unidade,µV

-57,123
12,5
-3
"""


def montar(pasta: Path, nome: str = "exportar.zip", conteudo_xml: str | None = None, gerado: str = "2026-10-31T10:00:00Z",
           nome_xml: str = "exportar.xml") -> Path:
    caminho = pasta / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"apple_health_export/{nome_xml}", conteudo_xml if conteudo_xml is not None else xml())
        z.writestr("apple_health_export/export_cda.xml", "<ClinicalDocument/>")
        z.writestr("apple_health_export/workout-routes/route_2026-10-30_6.00pm.gpx", GPX.format(gerado=gerado))
        z.writestr("apple_health_export/electrocardiograms/ecg_2026-10-30.csv", ECG.encode("utf-8"))
    return caminho


def _contar(url, modelo) -> int:
    with Session(create_engine(url)) as s:
        return s.scalar(select(func.count()).select_from(modelo))


def _todos(url, modelo) -> list:
    with Session(create_engine(url)) as s:
        return list(s.scalars(select(modelo).order_by(modelo.id)))


def _utc(m: datetime) -> datetime:
    return m.replace(tzinfo=timezone.utc) if m.tzinfo is None else m.astimezone(timezone.utc)


def test_importa_tudo(tmp_path, url):
    r = saude.importar(montar(tmp_path), create_engine(url))

    assert r["tabelas"] == {
        "saude_amostras": {"novos": 4, "repetidos": 0},  # FC, sono, variabilidade e a sistólica da Correlation
        "saude_treinos": {"novos": 1, "repetidos": 0},
        "saude_aneis": {"novos": 1, "repetidos": 0},
        "saude_rotas": {"novos": 1, "repetidos": 0},
        "saude_ecg": {"novos": 1, "repetidos": 0},
    }
    assert r["descartados"] == {"Record": 1}  # o de data inválida
    assert r["desconhecidos"] == {"Workout/Novidade": 1, "Correlation": 1, "Audiogram": 1}

    fc, sono, hrv, sistolica = _todos(url, SaudeAmostra)
    assert (fc.tipo, fc.valor, fc.valor_texto, fc.unidade) == ("HKQuantityTypeIdentifierHeartRate", 72.0, None,
                                                               "count/min")
    assert _utc(fc.inicio) == datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)  # 07:00 -0300 em UTC
    assert _utc(fc.criado_no_aparelho) == datetime(2026, 10, 30, 10, 1, tzinfo=timezone.utc)
    assert fc.metadados == {"HKMetadataKeyHeartRateMotionContext": "1"}
    assert "0x" not in fc.aparelho and "name:Apple Watch" in fc.aparelho
    assert (sono.valor, sono.valor_texto) == (None, "HKCategoryValueSleepAnalysisAsleepCore")
    assert hrv.batidas == [[60.0, "3:00:01,00 AM"], [62.0, "3:00:02,00 AM"]]
    assert sistolica.valor == 120.0

    (t,) = _todos(url, SaudeTreino)
    assert (t.tipo, t.duracao, t.unidade_duracao) == ("HKWorkoutActivityTypeTraditionalStrengthTraining", 45.5, "min")
    assert t.metadados == {"HKIndoorWorkout": "1"}
    assert t.estatisticas[0]["sum"] == "300" and t.eventos[0]["type"] == "HKWorkoutEventTypeSegment"
    assert t.zonas[0]["zonas"] == [{"maximum": "120", "duration": "5", "durationUnit": "min"}]
    assert t.amostras[0]["value"] == "130"

    (rota,) = _todos(url, SaudeRota)
    assert rota.treino_chave == t.chave and rota.quantidade == 2
    assert rota.pontos[0] == ["2026-10-30T21:00:00+00:00", -23.6, -46.5, 760.5, 1.2, 90.0, 1.5, 1.0]

    (anel,) = _todos(url, SaudeAnel)
    assert str(anel.data) == "2026-10-30" and anel.valores["activeEnergyBurned"] == "450"

    (e,) = _todos(url, SaudeEcg)
    assert e.amostras == [-57.123, 12.5, -3.0]  # vírgula decimal do iPhone em português
    assert e.cabecalho["Classificação"] == "Ritmo Sinusal" and e.cabecalho["Nascimento"] == "1 de jan. de 1990"
    assert _utc(e.registrado_em) == datetime(2026, 10, 30, 13, 20, 30, tzinfo=timezone.utc)

    (imp,) = _todos(url, SaudeImportacao)
    assert imp.ok and imp.arquivo == "exportar.zip" and imp.erro is None
    assert imp.perfil["HKCharacteristicTypeIdentifierBiologicalSex"] == "HKBiologicalSexMale"
    assert _utc(imp.data_export) == datetime(2026, 10, 31, 10, 5, tzinfo=timezone.utc)
    assert {s.importacao_id for s in _todos(url, SaudeAmostra)} == {imp.id}

    (a,) = _todos(url, Auditoria)
    assert (a.ferramenta, a.tabela, a.acao, a.autor, a.registro_id) == ("saude_importar", "saude_importacoes",
                                                                         "criar", "saude_importar", imp.id)
    assert a.dados["tabelas"]["saude_amostras"]["novos"] == 4
    assert "72" not in json.dumps(a.dados)  # só contagens, nenhum valor de saúde


def test_reimportar_nao_duplica(tmp_path, url):
    engine = create_engine(url)
    saude.importar(montar(tmp_path), engine)
    r = saude.importar(montar(tmp_path, nome="de-novo.zip", gerado="2026-11-07T10:00:00Z"), engine)
    assert all(c["novos"] == 0 and c["repetidos"] >= 1 for c in r["tabelas"].values()), r
    assert _contar(url, SaudeAmostra) == 4 and _contar(url, SaudeRota) == 1
    assert _contar(url, SaudeImportacao) == 2 and _contar(url, Auditoria) == 2


def test_mesma_amostra_com_outro_endereco_e_outro_fuso_e_repetida(tmp_path, url):
    # O endereço de memória do aparelho muda a cada export, e o iPhone pode exportar em outro fuso.
    engine = create_engine(url)
    saude.importar(montar(tmp_path), engine)
    r = saude.importar(montar(tmp_path, nome="b.zip", conteudo_xml=xml(endereco="11111111", fuso="+0000")), engine)
    assert r["tabelas"]["saude_amostras"] == {"novos": 0, "repetidos": 4}
    assert r["tabelas"]["saude_treinos"] == {"novos": 0, "repetidos": 1}


def test_dia_mais_cheio_e_amostra_nova_entram(tmp_path, url):
    engine = create_engine(url)
    saude.importar(montar(tmp_path), engine)
    nova = ('<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" '
            'startDate="2026-10-30 20:00:00 -0300" endDate="2026-10-30 20:10:00 -0300" value="500"/>')
    r = saude.importar(montar(tmp_path, nome="b.zip", conteudo_xml=xml(amostras=nova, anel_energia="620")), engine)
    assert r["tabelas"]["saude_amostras"] == {"novos": 1, "repetidos": 4}
    assert r["tabelas"]["saude_aneis"] == {"novos": 1, "repetidos": 0}  # o mesmo dia, mais cheio: linha nova
    assert _contar(url, SaudeAnel) == 2


def test_nome_do_xml_em_ingles_tambem_serve(tmp_path, url):
    r = saude.importar(montar(tmp_path, nome_xml="export.xml"), create_engine(url))
    assert r["tabelas"]["saude_amostras"]["novos"] == 4


@pytest.mark.parametrize("caso, motivo", [
    ("nao_zip", "não é um arquivo zip"),
    ("sem_xml", "não achei o XML"),
    ("entidade", "declara entidades"),
    ("quebrado", "está quebrado"),
])
def test_recusa_sem_gravar(tmp_path, url, caso, motivo):
    if caso == "nao_zip":
        arq = tmp_path / "x.zip"
        arq.write_bytes(b"isto nao e zip")
    elif caso == "sem_xml":
        arq = montar(tmp_path, conteudo_xml="<Outra/>")
    elif caso == "entidade":
        arq = montar(tmp_path, conteudo_xml=xml().replace("]>", '<!ENTITY a "aaaa">\n]>'))
    else:
        arq = montar(tmp_path, conteudo_xml=xml()[:-40])
    with pytest.raises(saude.Recusa, match=motivo):
        saude.importar(arq, create_engine(url))
    for modelo in (SaudeAmostra, SaudeTreino, SaudeImportacao, Auditoria):
        assert _contar(url, modelo) == 0


def test_comando_importar(tmp_path, url):
    env = {**os.environ, "DATABASE_URL_ESCRITA": url, "PYTHONIOENCODING": "utf-8"}
    ok = subprocess.run([sys.executable, "-m", "assistente.saude", "importar", str(montar(tmp_path))], cwd=SERVIDOR,
                        env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["tabelas"]["saude_amostras"]["novos"] == 4

    ruim = tmp_path / "ruim.zip"
    ruim.write_bytes(b"x")
    r = subprocess.run([sys.executable, "-m", "assistente.saude", "importar", str(ruim)], cwd=SERVIDOR, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 1 and "recusado" in r.stderr
    falha = _todos(url, SaudeImportacao)[-1]
    assert (falha.ok, falha.arquivo, falha.erro) == (False, "ruim.zip", "recusado: não é um arquivo zip")

    sem = subprocess.run([sys.executable, "-m", "assistente.saude", "importar", str(ruim)], cwd=SERVIDOR,
                         env={k: v for k, v in env.items() if k != "DATABASE_URL_ESCRITA"}, capture_output=True,
                         text=True)
    assert sem.returncode == 2 and "DATABASE_URL_ESCRITA" in sem.stderr


def _envelhecer(arq: Path, segundos: int = 600) -> None:
    antes = time.time() - segundos
    os.utime(arq, (antes, antes))


@pytest.fixture
def sem_espera(monkeypatch):
    """A espera conta também pelo ctime, que o teste não muda: depois do primeiro passo, tira a espera."""
    return lambda: monkeypatch.setattr(saude, "PARADO_S", 0)


def test_pasta_de_entrada(tmp_path, url, sem_espera):
    engine = create_engine(url)
    entrada, importados = tmp_path / "entrada", tmp_path / "importados"
    entrada.mkdir()
    recusados: dict = {}

    novo = montar(entrada, nome="agora.zip")  # acabou de chegar: espera ficar parado
    (entrada / ".syncthing.parcial.zip.tmp").write_bytes(b"x")
    assert saude.vigiar_uma_vez(entrada, importados, engine, recusados) == []
    _envelhecer(novo)
    assert saude.vigiar_uma_vez(entrada, importados, engine, recusados) == []  # chegou agora (ctime): espera
    sem_espera()

    (feito,) = saude.vigiar_uma_vez(entrada, importados, engine, recusados)
    assert feito["tabelas"]["saude_amostras"]["novos"] == 4
    assert not novo.exists() and (importados / "agora.zip").exists()

    segundo = montar(entrada, nome="semana-que-vem.zip", gerado="2026-11-07T10:00:00Z")
    _envelhecer(segundo)
    saude.vigiar_uma_vez(entrada, importados, engine, recusados)
    assert sorted(p.name for p in importados.iterdir()) == ["semana-que-vem.zip"]  # fica só o último

    ruim = entrada / "ruim.zip"
    ruim.write_bytes(b"x")
    _envelhecer(ruim)
    assert saude.vigiar_uma_vez(entrada, importados, engine, recusados) == []
    assert ruim.exists()  # recusado fica na entrada
    falhas = [i for i in _todos(url, SaudeImportacao) if not i.ok]
    assert len(falhas) == 1
    saude.vigiar_uma_vez(entrada, importados, engine, recusados)
    assert len([i for i in _todos(url, SaudeImportacao) if not i.ok]) == 1  # não tenta de novo sem mudar

    montar(entrada, nome="ruim.zip")  # o mesmo nome, agora certo
    _envelhecer(ruim, 300)
    (feito,) = saude.vigiar_uma_vez(entrada, importados, engine, recusados)
    assert not ruim.exists()


def test_arquivo_grande_com_memoria_estavel(tmp_path, url):
    # 20 mil amostras: a memória do importador não cresce com o tamanho do XML (leitura em fluxo e lotes).
    linhas = "\n".join(
        f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch de Teste" unit="count/min" '
        f'startDate="2026-10-29 {i // 3600 % 24:02d}:{i // 60 % 60:02d}:{i % 60:02d} -0300" '
        f'endDate="2026-10-29 {i // 3600 % 24:02d}:{i // 60 % 60:02d}:{i % 60:02d} -0300" value="{60 + i % 1000}"/>'
        for i in range(20_000))
    arq = montar(tmp_path, conteudo_xml=xml(amostras=linhas))
    tracemalloc.start()
    try:
        r = saude.importar(arq, create_engine(url))
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r["tabelas"]["saude_amostras"]["novos"] == 4 + 20_000
    assert pico < 40 * 1024 * 1024, pico


def test_migracao_0008_sobe_e_desce_sem_apagar(tmp_path):
    url = f"sqlite:///{tmp_path / 'migra.db'}"
    _alembic(url, "upgrade", "head")
    tabelas = set(inspect(create_engine(url)).get_table_names())
    assert {"saude_importacoes", "saude_amostras", "saude_treinos", "saude_rotas", "saude_aneis", "saude_ecg"} <= tabelas
    # A auditoria da 0001 usa now(), que o SQLite não tem: grava direto, com criado_em.
    agora = datetime(2026, 10, 30, tzinfo=timezone.utc)
    with Session(create_engine(url)) as s, s.begin():
        s.add(SaudeAmostra(chave="c" * 64, tipo="HKQuantityTypeIdentifierHeartRate", valor=72.0, inicio=agora,
                           fim=agora, origem="teste", criado_em=agora))
    _alembic(url, "downgrade", "0007")
    assert _contar(url, SaudeAmostra) == 1  # o downgrade não apaga
    _alembic(url, "upgrade", "head")
    assert _contar(url, SaudeAmostra) == 1


FC_REPETIDA = ('<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch de Teste" unit="count/min" '
               'startDate="2026-10-30 07:00:00 -0300" endDate="2026-10-30 07:00:00 -0300" value="72"/>')


def test_a_mesma_amostra_duas_vezes_no_mesmo_arquivo_entra_uma(tmp_path, url):
    r = saude.importar(montar(tmp_path, conteudo_xml=xml(amostras=FC_REPETIDA)), create_engine(url))
    assert r["tabelas"]["saude_amostras"] == {"novos": 4, "repetidos": 1}


def test_ecg_com_ponto_decimal(tmp_path, url):
    # iPhone em inglês: ponto decimal nas amostras.
    linha = saude.ecg("Name,Teste\nRecorded Date,2026-10-30 10:20:30 -0300\nUnit,µV\n\n-57.123\n12.5\n-3\n".encode())
    assert linha["amostras"] == [-57.123, 12.5, -3.0]
    assert "-57.123" not in linha["cabecalho"]
    assert _utc(linha["registrado_em"]) == datetime(2026, 10, 30, 13, 20, 30, tzinfo=timezone.utc)


def test_entidade_depois_de_1_mb_tambem_e_recusada(tmp_path, url):
    comentario = "<!-- <HealthData " + "x" * (1024 * 1024 + 10) + " -->\n"
    conteudo = xml().replace("]>", comentario + '<!ENTITY a "aaaa">\n]>')
    with pytest.raises(saude.Recusa, match="declara entidades"):
        saude.importar(montar(tmp_path, conteudo_xml=conteudo), create_engine(url))
    assert _contar(url, SaudeAmostra) == 0


def test_entidade_num_gpx_recusa_o_arquivo(tmp_path, url):
    arq = montar(tmp_path)
    with zipfile.ZipFile(arq, "a") as z:
        z.writestr("apple_health_export/workout-routes/route_ruim.gpx",
                   '<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "aaaa">]><gpx>&a;</gpx>')
    with pytest.raises(saude.Recusa, match="declara entidades"):
        saude.importar(arq, create_engine(url))
    assert _contar(url, SaudeAmostra) == 0


def test_zip_corrompido_no_meio_e_recusa(tmp_path, url):
    arq = montar(tmp_path)
    dados = bytearray(arq.read_bytes())
    with zipfile.ZipFile(arq) as z:
        info = z.getinfo("apple_health_export/exportar.xml")
    meio = info.header_offset + 30 + len(info.filename) + info.compress_size // 2
    dados[meio] ^= 0xFF  # um byte trocado no meio do XML compactado: CRC ou zlib falham na leitura
    arq.write_bytes(bytes(dados))
    with pytest.raises(saude.Recusa, match="corrompido|quebrado"):
        saude.importar(arq, create_engine(url))


def test_falha_do_banco_tenta_de_novo_com_espera(tmp_path, url, monkeypatch, sem_espera):
    sem_espera()
    engine = create_engine(url)
    entrada, importados = tmp_path / "entrada", tmp_path / "importados"
    entrada.mkdir()
    arq = montar(entrada)
    _envelhecer(arq)
    real = saude.importar
    chamadas = []

    def falha_uma_vez(caminho, eng):
        chamadas.append(caminho.name)
        if len(chamadas) == 1:
            raise OSError("banco fora do ar")
        return real(caminho, eng)

    monkeypatch.setattr(saude, "importar", falha_uma_vez)
    memoria: dict = {}
    assert saude.vigiar_uma_vez(entrada, importados, engine, memoria) == []
    assert memoria["exportar.zip"]["estado"] == "falha" and arq.exists()
    assert saude.vigiar_uma_vez(entrada, importados, engine, memoria) == []  # ainda na espera
    assert len(chamadas) == 1
    memoria["exportar.zip"]["proxima"] = 0  # a espera passou
    (feito,) = saude.vigiar_uma_vez(entrada, importados, engine, memoria)
    assert feito["tabelas"]["saude_amostras"]["novos"] == 4 and not arq.exists()


def test_falha_ao_mover_nao_reimporta_em_laco(tmp_path, url, monkeypatch, sem_espera, caplog):
    sem_espera()
    engine = create_engine(url)
    entrada, importados = tmp_path / "entrada", tmp_path / "importados"
    entrada.mkdir()
    arq = montar(entrada)
    _envelhecer(arq)

    def sem_espaco(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(saude.shutil, "move", sem_espaco)
    memoria: dict = {}
    with caplog.at_level("INFO", logger="assistente.saude"):
        assert len(saude.vigiar_uma_vez(entrada, importados, engine, memoria)) == 1
        assert saude.vigiar_uma_vez(entrada, importados, engine, memoria) == []
    assert arq.exists() and _contar(url, SaudeImportacao) == 1
    assert "não consegui movê-lo" in caplog.text


def test_log_e_auditoria_sem_valor_de_saude(tmp_path, url, monkeypatch, sem_espera, caplog):
    sem_espera()
    engine = create_engine(url)
    entrada, importados = tmp_path / "entrada", tmp_path / "importados"
    entrada.mkdir()
    valor = "98765.4321"  # valor único, fácil de achar se vazar
    nova = (f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" '
            f'startDate="2026-10-30 20:00:00 -0300" endDate="2026-10-30 20:10:00 -0300" value="{valor}"/>')
    _envelhecer(montar(entrada, conteudo_xml=xml(amostras=nova)))
    ruim = entrada / "ruim.zip"
    ruim.write_bytes(b"x")
    _envelhecer(ruim)
    with caplog.at_level("DEBUG"):
        saude.vigiar_uma_vez(entrada, importados, engine, {})
    assert "importado" in caplog.text and "recusado" in caplog.text
    assert valor not in caplog.text and "98765" not in caplog.text
    for a in _todos(url, Auditoria):
        assert "98765" not in json.dumps(a.dados)
    for i in _todos(url, SaudeImportacao):
        assert "98765" not in json.dumps(i.contagens) + (i.erro or "")


def test_origem_renomeada_gera_aviso(tmp_path, url, monkeypatch, caplog):
    # O relógio mudou de nome: o export novo reescreve as amostras antigas com a origem nova, e elas entram de novo.
    monkeypatch.setattr(saude, "AVISO_ANTIGAS_MINIMO", 1)
    engine = create_engine(url)
    primeira = saude.importar(montar(tmp_path), engine)
    assert primeira["amostras_antigas_novas"] == 0  # sem export anterior, não há o que comparar
    renomeado = xml().replace("Apple Watch de Teste", "Relogio Novo")
    with caplog.at_level("WARNING", logger="assistente.saude"):
        r = saude.importar(montar(tmp_path, nome="b.zip", conteudo_xml=renomeado), engine)
    assert r["amostras_antigas_novas"] == 3  # frequência cardíaca, sono e variabilidade, do relógio
    assert "3 amostras de antes do último export" in caplog.text


def test_amostra_nova_de_verdade_nao_gera_aviso(tmp_path, url, monkeypatch, caplog):
    monkeypatch.setattr(saude, "AVISO_ANTIGAS_MINIMO", 1)
    engine = create_engine(url)
    saude.importar(montar(tmp_path), engine)
    nova = ('<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" '
            'startDate="2026-11-05 20:00:00 -0300" endDate="2026-11-05 20:10:00 -0300" value="500"/>')
    with caplog.at_level("WARNING", logger="assistente.saude"):
        r = saude.importar(montar(tmp_path, nome="b.zip", conteudo_xml=xml(amostras=nova)), engine)
    assert r["tabelas"]["saude_amostras"]["novos"] == 1 and r["amostras_antigas_novas"] == 0
    assert "antes do último export" not in caplog.text
