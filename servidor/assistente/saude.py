"""Importação do `export.zip` do app Saúde do iPhone (Ficha 14, PLANO 5b.1).

    python -m assistente.saude importar <export.zip>
    python -m assistente.saude vigiar <pasta de entrada> <pasta dos importados>

`importar` lê o zip sem extrair e grava, numa transação só, as amostras, os treinos, as rotas GPS, os anéis e os
eletrocardiogramas. A mesma coisa já gravada (mesma `chave`) conta como repetida: reimportar não duplica.
Imprime as contagens em JSON. Código 0 se gravou; 1 se o arquivo foi recusado; 2 se o banco falhou ou falta a
variável (sem a URL na mensagem).

`vigiar` é a pasta de entrada (calibração, item 4): a cada 5 min, importa cada `.zip` parado há 2 min e o move para
a pasta dos importados, onde fica só o último (ele guarda o `export_cda.xml` e tudo que não vira linha). Arquivo
recusado fica na entrada, e só é tentado de novo quando mudar; falha do banco é tentada de novo, com espera.

Tudo é dado de fora: o XML é lido em fluxo, sem entidades (recusa o arquivo que declarar alguma), cada texto é
limpo e cortado ao tamanho da coluna. Nada de valor de saúde vai para log ou mensagem de erro.
Grava pela conexão de escrita (`DATABASE_URL_ESCRITA`, só INSERT e SELECT nas tabelas de saúde), com UMA linha de
`auditoria` e uma de `saude_importacoes` por importação, só com contagens.
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import zipfile
import zlib
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator
from xml.etree import ElementTree as ET
from xml.parsers import expat

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .db import opcoes_engine
from .modelos import Auditoria, SaudeAmostra, SaudeAnel, SaudeEcg, SaudeImportacao, SaudeRota, SaudeTreino

log = logging.getLogger("assistente.saude")

AUTOR = "saude_importar"
LOTE = 2000  # linhas por executemany; o SQLAlchemy as divide em INSERTs dentro do limite de parâmetros
MAX_MEMBRO = 8 * 1024**3  # 8 GB descompactados por arquivo do zip (o XML real tem 821 MB)
MAX_MEMBROS = 50_000
MAX_CSV = 10 * 1024 * 1024  # um eletrocardiograma real tem ~120 KB
PAUSA_VIGIA_S = 300
# Amostra de antes do último export entrando como nova: a origem pode ter sido renomeada, e a chave usa o nome dela
# (decisão do Leonardo, 2026-10-31: avisar no log). Aviso a partir de 100 amostras e 1% das amostras do arquivo.
AVISO_ANTIGAS_MINIMO = 100
AVISO_ANTIGAS_FRACAO = 0.01
ESPERA_MAXIMA_S = 6 * 3600  # falha do banco: tenta de novo com espera dobrando até 6 h
PARADO_S = 120
GPX = "{http://www.topografix.com/GPX/1/1}"
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ENDERECO = re.compile(r"<HKDevice: 0x[0-9a-fA-F]+>, ?")
_AMOSTRA_ECG = re.compile(r"-?\d+(?:[.,]\d+)?")  # vírgula decimal (iPhone em português) ou ponto


class Recusa(ValueError):
    """Arquivo que não é um export do app Saúde. A mensagem nunca leva valor de saúde."""


# --- conversões -----------------------------------------------------------------------------------------------


def _texto(valor: Any, tamanho: int | None = None) -> str | None:
    if valor is None:
        return None
    limpo = _CONTROLE.sub(" ", str(valor).encode("utf-8", "replace").decode("utf-8"))
    return limpo[:tamanho] if tamanho else limpo


def _atributos(el: ET.Element) -> dict:
    return {_texto(k, 100): _texto(v, 2000) for k, v in el.attrib.items()}


def momento(texto: str | None) -> datetime | None:
    """Data do export ("2018-04-05 02:17:18 -0300") ou ISO ("2023-05-05T22:13:10Z"), sempre em UTC."""
    if not texto:
        return None
    t = texto.strip()
    if len(t) == 25 and t[10] == " " and t[19] == " ":  # formato do app Saúde: o mais comum, sem strptime (lento)
        t = f"{t[:10]}T{t[11:19]}{t[20:23]}:{t[23:25]}"
    try:
        m = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    if m.tzinfo is None:
        return None
    return m.astimezone(timezone.utc)


def _numero(texto: str | None) -> float | None:
    if texto is None:
        return None
    try:
        n = float(texto)
    except ValueError:
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None  # NaN e infinito não entram


def chave(*partes: Any) -> str:
    """sha256 dos campos que identificam o dado. Data entra em ISO UTC; número, normalizado (72 = 72.0)."""
    def norma(p: Any) -> str:
        if isinstance(p, datetime):
            return p.astimezone(timezone.utc).isoformat()
        if isinstance(p, float):
            return repr(p)
        return "" if p is None else str(p)
    return hashlib.sha256("\x1f".join(norma(p) for p in partes).encode("utf-8")).hexdigest()


def _metadados(el: ET.Element) -> dict | None:
    meta = {_texto(m.get("key"), 200): _texto(m.get("value"), 2000) for m in el.findall("MetadataEntry")}
    return meta or None


def _origem(el: ET.Element) -> dict:
    aparelho = el.get("device")
    return {
        "criado_no_aparelho": momento(el.get("creationDate")),
        "origem": _texto(el.get("sourceName") or "?", 120),
        "versao_origem": _texto(el.get("sourceVersion"), 60),
        # O endereço de memória muda a cada export: tirá-lo deixa o texto estável.
        "aparelho": _texto(_ENDERECO.sub("", aparelho)) if aparelho else None,
        "metadados": _metadados(el),
    }


# --- leitura do export ----------------------------------------------------------------------------------------


def amostra(el: ET.Element) -> dict | None:
    """Linha de `saude_amostras` para um `Record`; None se faltar tipo ou data."""
    tipo, inicio, fim = el.get("type"), momento(el.get("startDate")), momento(el.get("endDate"))
    if not tipo or inicio is None or fim is None:
        return None
    bruto = el.get("value")
    valor = _numero(bruto)
    texto = None if valor is not None else _texto(bruto, 120)
    origem = _origem(el)
    lista = el.find("HeartRateVariabilityMetadataList")
    batidas = None
    if lista is not None:
        batidas = [[_numero(b.get("bpm")), _texto(b.get("time"), 40)] for b in lista.findall("InstantaneousBeatsPerMinute")]
    unidade = _texto(el.get("unit"), 40)
    return {
        "chave": chave("amostra", tipo, inicio, fim, valor if valor is not None else texto, unidade, origem["origem"]),
        "tipo": _texto(tipo, 100), "valor": valor, "valor_texto": texto, "unidade": unidade,
        "inicio": inicio, "fim": fim, **origem, "batidas": batidas,
    }


def treino(el: ET.Element, desconhecidos: Counter) -> tuple[dict | None, str | None]:
    """(linha de `saude_treinos`, caminho do .gpx da rota) para um `Workout`."""
    tipo, inicio, fim = el.get("workoutActivityType"), momento(el.get("startDate")), momento(el.get("endDate"))
    if not tipo or inicio is None or fim is None:
        return None, None
    origem = _origem(el)
    estatisticas, eventos, zonas, amostras, rota = [], [], [], [], None
    for filho in el:
        if filho.tag == "MetadataEntry":
            continue
        if filho.tag == "WorkoutStatistics":
            estatisticas.append(_atributos(filho))
        elif filho.tag == "WorkoutEvent":
            eventos.append({**_atributos(filho), "metadados": _metadados(filho)})
        elif filho.tag == "WorkoutZoneGroup":
            zonas.append({**_atributos(filho), "zonas": [_atributos(z) for z in filho.findall("WorkoutZone")]})
        elif filho.tag == "Record":
            amostras.append({**_atributos(filho), "metadados": _metadados(filho)})
        elif filho.tag == "WorkoutRoute":
            ref = filho.find("FileReference")
            rota = ref.get("path") if ref is not None else None
        else:
            desconhecidos[f"Workout/{_texto(filho.tag, 60)}"] += 1
    linha = {
        "chave": chave("treino", tipo, inicio, fim, origem["origem"]),
        "tipo": _texto(tipo, 100), "inicio": inicio, "fim": fim,
        "duracao": _numero(el.get("duration")), "unidade_duracao": _texto(el.get("durationUnit"), 20),
        **origem, "estatisticas": estatisticas, "eventos": eventos, "zonas": zonas, "amostras": amostras,
    }
    return linha, rota


def anel(el: ET.Element) -> dict | None:
    try:
        dia = date.fromisoformat(el.get("dateComponents") or "")
    except ValueError:
        return None
    valores = {k: v for k, v in _atributos(el).items() if k != "dateComponents"}
    return {"chave": chave("anel", dia.isoformat(), json.dumps(valores, sort_keys=True)), "data": dia, "valores": valores}


def rota(fluxo: BinaryIO, treino_chave: str | None) -> dict | None:
    """Linha de `saude_rotas` para um .gpx. A chave vem dos pontos: o cabeçalho muda a cada export."""
    pontos = []
    for _, el in ET.iterparse(fluxo):
        if el.tag != f"{GPX}trkpt":
            continue
        ext = el.find(f"{GPX}extensions")
        def campo(nome: str, onde: ET.Element | None = el) -> float | None:
            if onde is None:
                return None
            achado = onde.find(f"{GPX}{nome}")
            return _numero(achado.text) if achado is not None else None
        hora = el.find(f"{GPX}time")
        quando = momento(hora.text if hora is not None else None)
        pontos.append([quando.isoformat() if quando else None, _numero(el.get("lat")), _numero(el.get("lon")),
                       campo("ele"), campo("speed", ext), campo("course", ext), campo("hAcc", ext), campo("vAcc", ext)])
        el.clear()
    if not pontos:
        return None
    horas = [p[0] for p in pontos if p[0]]
    return {"chave": chave("rota", json.dumps(pontos)), "treino_chave": treino_chave,
            "inicio": momento(horas[0]) if horas else None, "fim": momento(horas[-1]) if horas else None,
            "quantidade": len(pontos), "pontos": pontos}


def ecg(conteudo: bytes) -> dict | None:
    """Linha de `saude_ecg` para um CSV. O iPhone em português usa vírgula decimal ("-57,123"); em inglês, ponto."""
    texto = conteudo.decode("utf-8-sig", "replace")
    cabecalho, amostras = {}, []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if _AMOSTRA_ECG.fullmatch(linha):
            amostras.append(float(linha.replace(",", ".")))
            continue
        if amostras:  # texto depois das amostras: não é o formato conhecido
            return None
        campos = next(csv.reader([linha]))
        cabecalho[_texto(campos[0], 100)] = _texto(",".join(campos[1:]), 500)
    if not amostras:
        return None
    registrado = next((momento(v) for k, v in cabecalho.items() if k and k.lower().startswith(("data do registro",
                                                                                                "recorded date"))), None)
    return {"chave": chave("ecg", hashlib.sha256(conteudo).hexdigest()), "registrado_em": registrado,
            "cabecalho": cabecalho, "amostras": amostras}


class _Parar(Exception):
    pass


def raiz_sem_entidades(fluxo: BinaryIO) -> str | None:
    """Nome do elemento raiz, lendo só o começo do arquivo. Recusa o que declarar entidade (o DTD vem todo antes da
    raiz, então parar nela basta). None se não for XML."""
    p = expat.ParserCreate()
    raiz: list[str] = []

    def entidade(*_args) -> None:
        raise Recusa("o arquivo declara entidades (um export do app Saúde não declara)")

    def inicio(nome: str, _atributos) -> None:
        raiz.append(nome)
        raise _Parar

    p.EntityDeclHandler = entidade
    p.UnparsedEntityDeclHandler = entidade
    p.StartElementHandler = inicio
    try:
        while bloco := fluxo.read(64 * 1024):
            p.Parse(bloco, False)
        p.Parse(b"", True)
    except _Parar:
        pass
    except expat.ExpatError:
        return None
    return raiz[0] if raiz else None


def achar_xml(z: zipfile.ZipFile) -> str:
    """O XML principal pelo conteúdo: o nome muda com o idioma do iPhone ("exportar.xml" em português)."""
    for info in z.infolist():
        nome = info.filename
        if not nome.lower().endswith(".xml") or nome.count("/") > 1 or "cda" in nome.lower().rsplit("/", 1)[-1]:
            continue
        with z.open(info) as f:
            if raiz_sem_entidades(f) == "HealthData":
                return nome
    raise Recusa("não achei o XML do app Saúde no zip")


def _conferir_zip(z: zipfile.ZipFile) -> None:
    infos = z.infolist()
    if len(infos) > MAX_MEMBROS:
        raise Recusa(f"o zip tem mais de {MAX_MEMBROS} arquivos")
    if any(i.file_size > MAX_MEMBRO for i in infos):
        raise Recusa(f"um arquivo do zip passa de {MAX_MEMBRO // 1024**3} GB descompactado")


# --- gravação -------------------------------------------------------------------------------------------------


def _utc(m: datetime) -> datetime:
    # O SQLite (testes) devolve sem fuso o que gravou em UTC; o Postgres devolve com fuso.
    return m.replace(tzinfo=timezone.utc) if m.tzinfo is None else m.astimezone(timezone.utc)


class _Gravador:
    """Junta linhas por tabela e grava em lotes com INSERT ... ON CONFLICT (chave) DO NOTHING."""

    def __init__(self, s: Session, importacao_id: int, corte: datetime | None = None):
        self.s, self.importacao_id, self.corte = s, importacao_id, corte
        self.antigas = 0  # amostras novas com início antes de `corte` (data do último export importado)
        self.dialeto = postgresql if s.get_bind().dialect.name == "postgresql" else sqlite
        self.filas: dict[type, list[dict]] = {}
        self.contagens: dict[str, dict[str, int]] = {}

    def add(self, modelo: type, linha: dict, lote: int = LOTE) -> None:
        fila = self.filas.setdefault(modelo, [])
        fila.append({**linha, "importacao_id": self.importacao_id})
        if len(fila) >= lote:
            self._gravar(modelo)

    def _gravar(self, modelo: type) -> None:
        fila = self.filas.get(modelo)
        if not fila:
            return
        # executemany com o mesmo comando (o SQLAlchemy junta em INSERTs de várias linhas e reaproveita o comando
        # compilado); o RETURNING só traz as linhas que entraram, e assim conta as novas.
        tabela = modelo.__table__
        comando = self.dialeto.insert(tabela).on_conflict_do_nothing(index_elements=["chave"]).returning(
            tabela.c.id, *([tabela.c.inicio] if modelo is SaudeAmostra else []))
        linhas = self.s.connection().execute(comando, fila).all()
        novos = len(linhas)
        if modelo is SaudeAmostra and self.corte is not None:
            self.antigas += sum(1 for linha in linhas if _utc(linha.inicio) < self.corte)
        conta = self.contagens.setdefault(modelo.__tablename__, {"novos": 0, "repetidos": 0})
        conta["novos"] += novos
        conta["repetidos"] += len(fila) - novos
        fila.clear()

    def terminar(self) -> dict[str, dict[str, int]]:
        for modelo in list(self.filas):
            self._gravar(modelo)
        return self.contagens


def _ler_xml(z: zipfile.ZipFile, nome: str, g: _Gravador, desconhecidos: Counter) -> tuple[dict, dict[str, str]]:
    """Grava amostras, treinos e anéis. Devolve ({data_export, perfil}, caminho do .gpx -> chave do treino)."""
    extra: dict = {"data_export": None, "perfil": None}
    rotas: dict[str, str] = {}
    descartados = Counter()
    profundidade, raiz = 0, None
    with z.open(nome) as f:
        for evento, el in ET.iterparse(f, events=("start", "end")):
            if evento == "start":
                if raiz is None:
                    raiz = el
                    if el.tag != "HealthData":
                        raise Recusa("a raiz do XML não é HealthData")
                profundidade += 1
                continue
            profundidade -= 1
            if profundidade != 1:
                continue
            tag = el.tag
            if tag == "Record":
                linha = amostra(el)
                g.add(SaudeAmostra, linha) if linha else descartados.update(["Record"])
            elif tag == "Workout":
                linha, caminho = treino(el, desconhecidos)
                if linha:
                    g.add(SaudeTreino, linha)
                    if caminho:
                        rotas[caminho.lstrip("/")] = linha["chave"]
                else:
                    descartados["Workout"] += 1
            elif tag == "ActivitySummary":
                linha = anel(el)
                g.add(SaudeAnel, linha) if linha else descartados.update(["ActivitySummary"])
            elif tag == "Correlation":  # pressão arterial e afins: as amostras de dentro entram como amostras
                desconhecidos["Correlation"] += 1
                for filho in el.findall("Record"):
                    linha = amostra(filho)
                    g.add(SaudeAmostra, linha) if linha else descartados.update(["Record"])
            elif tag == "ExportDate":
                extra["data_export"] = momento(el.get("value"))
            elif tag == "Me":
                extra["perfil"] = _atributos(el)
            else:
                desconhecidos[_texto(tag, 60)] += 1
            raiz.clear()  # sem isto, a raiz guarda um elemento vazio por amostra (1,7 milhão)
    extra["descartados"] = dict(descartados)
    return extra, rotas


def importar(caminho: Path, engine: Engine) -> dict:
    """Importa o export.zip numa transação. Levanta `Recusa` (arquivo) ou o erro do banco."""
    inicio = datetime.now(timezone.utc)
    try:
        z = zipfile.ZipFile(caminho)
    except (zipfile.BadZipFile, OSError):
        raise Recusa("não é um arquivo zip") from None
    with z, Session(engine) as s, s.begin():
        _conferir_zip(z)
        try:
            nome_xml = achar_xml(z)
        except (zipfile.BadZipFile, EOFError, zlib.error):
            raise Recusa("o zip está corrompido") from None
        imp = SaudeImportacao(inicio=inicio, fim=inicio, ok=False, arquivo=_texto(caminho.name, 200), contagens={})
        corte = s.scalar(select(func.max(SaudeImportacao.data_export)).where(SaudeImportacao.ok.is_(True)))
        s.add(imp)
        s.flush()
        g = _Gravador(s, imp.id, _utc(corte) if corte else None)
        desconhecidos: Counter = Counter()
        try:
            extra, rotas = _ler_xml(z, nome_xml, g, desconhecidos)
            _ler_anexos(z, nome_xml, g, rotas, desconhecidos)
        except ET.ParseError:
            raise Recusa("o XML do app Saúde está quebrado") from None
        except (zipfile.BadZipFile, EOFError, zlib.error):  # CRC errado ou zip cortado no meio da leitura
            raise Recusa("o zip está corrompido") from None
        tabelas = g.terminar()
        contagens = {"tabelas": tabelas, "desconhecidos": dict(desconhecidos), "descartados": extra["descartados"],
                     "amostras_antigas_novas": g.antigas}
        amostras = tabelas.get("saude_amostras", {"novos": 0, "repetidos": 0})
        if g.antigas >= max(AVISO_ANTIGAS_MINIMO, AVISO_ANTIGAS_FRACAO * (amostras["novos"] + amostras["repetidos"])):
            log.warning("saude: %d amostras de antes do último export entraram como novas; se o relógio ou o iPhone "
                        "mudou de nome, elas podem repetir as antigas com outra origem (Ficha 14)", g.antigas)
        imp.ok, imp.fim, imp.contagens = True, datetime.now(timezone.utc), contagens
        imp.data_export, imp.perfil = extra["data_export"], extra["perfil"]
        s.add(Auditoria(ferramenta="saude_importar", tabela="saude_importacoes", registro_id=imp.id, acao="criar",
                        autor=AUTOR, dados={"importacao": imp.id, **contagens}))
        resultado = {"importacao": imp.id, **contagens}
    return resultado


def _ler_anexos(z: zipfile.ZipFile, nome_xml: str, g: _Gravador, rotas: dict[str, str], desconhecidos: Counter) -> None:
    """Rotas .gpx e eletrocardiogramas .csv; o resto do zip só é contado."""
    for info in z.infolist():
        nome = info.filename
        baixo = nome.lower()
        if info.is_dir() or nome == nome_xml:
            continue
        if baixo.endswith(".gpx"):
            caminho_rota = "workout-routes/" + nome.rsplit("/", 1)[-1]
            with z.open(info) as f:
                if raiz_sem_entidades(f) != "gpx":
                    desconhecidos["rota ilegível"] += 1
                    continue
            with z.open(info) as f:
                try:
                    linha = rota(f, rotas.get(caminho_rota))
                except ET.ParseError:
                    linha = None
            g.add(SaudeRota, linha, lote=20) if linha else desconhecidos.update(["rota ilegível"])
        elif "electrocardiograms/" in baixo and baixo.endswith(".csv"):
            if info.file_size > MAX_CSV:
                desconhecidos["ecg grande demais"] += 1
                continue
            linha = ecg(z.read(info))
            g.add(SaudeEcg, linha, lote=20) if linha else desconhecidos.update(["ecg ilegível"])
        elif "cda" in baixo.rsplit("/", 1)[-1] and baixo.endswith(".xml"):
            continue  # cópia clínica dos mesmos dados; fica no zip guardado (calibração, item 3)
        else:
            desconhecidos[f"arquivo .{baixo.rsplit('.', 1)[-1][:10]}"] += 1


def anotar_falha(engine: Engine, arquivo: str, erro: str) -> None:
    """Linha de importação com ok falso: o arquivo foi recusado ou o banco falhou no meio (nada ficou gravado)."""
    agora = datetime.now(timezone.utc)
    with Session(engine) as s, s.begin():
        s.add(SaudeImportacao(inicio=agora, fim=agora, ok=False, arquivo=_texto(arquivo, 200), contagens={},
                              erro=_texto(erro, 300)))


# --- pasta de entrada -----------------------------------------------------------------------------------------


def _prontos(entrada: Path, agora: float) -> Iterator[Path]:
    """Os .zip parados há PARADO_S. O Syncthing grava em `.syncthing.*.tmp` e só depois renomeia; ele copia o mtime
    do Mac, então a espera conta também pelo ctime (quando o arquivo chegou aqui)."""
    for arq in sorted(entrada.iterdir()):
        if arq.is_file() and arq.suffix.lower() == ".zip" and not arq.name.startswith("."):
            st = arq.stat()
            if agora - max(st.st_mtime, st.st_ctime) >= PARADO_S:
                yield arq


def vigiar_uma_vez(entrada: Path, importados: Path, engine: Engine, memoria: dict[str, dict]) -> list[dict]:
    """Uma passada pela pasta de entrada. `memoria` lembra, por nome e marca (tamanho, mtime), o que já foi recusado
    ou importado (não repete enquanto o arquivo não mudar) e o que falhou no banco (tenta de novo, com espera)."""
    feitos = []
    agora = time.time()
    for arq in _prontos(entrada, agora):
        st = arq.stat()
        marca = (st.st_size, st.st_mtime)
        antes = memoria.get(arq.name)
        if antes and antes["marca"] == marca:
            if antes["estado"] in ("recusado", "importado"):
                continue
            if agora < antes["proxima"]:
                continue
        try:
            resultado = importar(arq, engine)
        except Recusa as e:
            log.error("saude: %s recusado: %s", arq.name, e)
            memoria[arq.name] = {"marca": marca, "estado": "recusado"}
            _anotar_sem_falhar(engine, arq.name, f"recusado: {e}")
            continue
        except Exception as e:  # noqa: BLE001 (sem traceback: os parâmetros do SQL levariam valores de saúde ao log)
            # Banco fora do ar (atualizar.sh, reinício): o arquivo está bom; tenta de novo com espera dobrando.
            tentativas = antes["tentativas"] + 1 if antes and antes["marca"] == marca and antes["estado"] == "falha" else 1
            espera = min(PAUSA_VIGIA_S * 2 ** (tentativas - 1), ESPERA_MAXIMA_S)
            log.error("saude: %s não entrou (%s); tento de novo em %d min", arq.name, type(e).__name__, espera // 60)
            memoria[arq.name] = {"marca": marca, "estado": "falha", "tentativas": tentativas, "proxima": agora + espera}
            _anotar_sem_falhar(engine, arq.name, f"falha ao gravar ({type(e).__name__})")
            continue
        # Já está no banco: mesmo que mover falhe, não importa de novo enquanto o arquivo não mudar.
        memoria[arq.name] = {"marca": marca, "estado": "importado"}
        tabelas = resultado["tabelas"]
        log.info("saude: %s importado (%s)", arq.name,
                 ", ".join(f"{t}: {c['novos']} novos" for t, c in sorted(tabelas.items())))
        feitos.append(resultado)
        try:
            importados.mkdir(parents=True, exist_ok=True)
            destino = importados / arq.name
            shutil.move(str(arq), destino)
            for velho in importados.iterdir():  # fica só o último: ele tem tudo (o export é o histórico inteiro)
                if velho.is_file() and velho != destino and velho.suffix.lower() == ".zip":
                    velho.unlink()
        except OSError as e:
            log.error("saude: %s importado, mas não consegui movê-lo para importados (%s); tire-o da entrada",
                      arq.name, type(e).__name__)
            continue
        memoria.pop(arq.name, None)
    return feitos


def _anotar_sem_falhar(engine: Engine, arquivo: str, erro: str) -> None:
    try:
        anotar_falha(engine, arquivo, erro)
    except Exception as e:  # noqa: BLE001
        log.error("saude: não consegui anotar a falha (%s)", type(e).__name__)


# --- linha de comando -----------------------------------------------------------------------------------------


def _engine() -> Engine | None:
    url = os.environ.get("DATABASE_URL_ESCRITA", "")
    if not url:
        print("saude: DATABASE_URL_ESCRITA não definida.", file=sys.stderr)
        return None
    opcoes = opcoes_engine(url)
    opcoes.get("connect_args", {}).pop("options", None)  # sem o prazo de 5 s por comando: o lote grande passa dele
    return create_engine(url, **opcoes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistente.saude", description="Dados do app Saúde (Ficha 14).")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("importar", help="Importa um export.zip do app Saúde.")
    p.add_argument("arquivo", type=Path)
    p = sub.add_parser("vigiar", help="Importa sozinho cada .zip que chegar na pasta de entrada.")
    p.add_argument("entrada", type=Path)
    p.add_argument("importados", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = _engine()
    if engine is None:
        return 2
    try:
        if args.comando == "importar":
            try:
                resultado = importar(args.arquivo, engine)
            except Recusa as e:
                print(f"saude: recusado: {e}", file=sys.stderr)
                _anotar_sem_falhar(engine, args.arquivo.name, f"recusado: {e}")
                return 1
            except Exception as e:  # noqa: BLE001 (qualquer falha do banco vira código 2, sem a URL com senha)
                print(f"saude: não consegui gravar ({type(e).__name__}); nada foi importado.", file=sys.stderr)
                return 2
            print(json.dumps(resultado, ensure_ascii=False))
            return 0
        if not args.entrada.is_dir():
            print("saude: a pasta de entrada não existe.", file=sys.stderr)
            return 2
        log.info("saude: vigiando %s a cada %d min", args.entrada, PAUSA_VIGIA_S // 60)
        memoria: dict[str, dict] = {}
        while True:
            try:
                vigiar_uma_vez(args.entrada, args.importados, engine, memoria)
            except OSError as e:
                log.error("saude: não consegui ler a pasta (%s)", type(e).__name__)
            time.sleep(PAUSA_VIGIA_S)
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
