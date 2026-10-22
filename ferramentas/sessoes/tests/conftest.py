"""Põe `ferramentas/sessoes/` no caminho de importação e prepara o transcript sintético."""
from __future__ import annotations

import os
import sys

import pytest

PASTA_SESSOES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "transcript.jsonl")
SESSAO = "11111111-2222-4333-8444-555555555555"

if PASTA_SESSOES not in sys.path:
    sys.path.insert(0, PASTA_SESSOES)


@pytest.fixture
def estado(tmp_path, monkeypatch):
    """Pasta de estado temporária e máquina fixa."""
    pasta = tmp_path / "estado"
    monkeypatch.setenv("ASSISTENTE_SESSOES_DIR", str(pasta))
    monkeypatch.setenv("ASSISTENTE_MAQUINA", "maquina-teste")
    return pasta


@pytest.fixture
def projeto(tmp_path):
    """Repositório falso (pasta com `.git`) com uma subpasta."""
    raiz = tmp_path / "meu-projeto"
    (raiz / ".git").mkdir(parents=True)
    (raiz / "servidor").mkdir()
    return raiz


def escrever_transcript(destino, raiz, sem=()):
    """Copia o fixture trocando `__RAIZ__` pela raiz; tira as linhas que contêm algum texto de `sem`."""
    with open(FIXTURE, encoding="utf-8") as f:
        linhas = f.readlines()
    raiz_json = str(raiz).replace("\\", "\\\\")
    with open(destino, "w", encoding="utf-8") as f:
        for linha in linhas:
            if any(s in linha for s in sem):
                continue
            f.write(linha.replace("__RAIZ__", raiz_json))
    return str(destino)


@pytest.fixture
def transcript(tmp_path, projeto):
    return escrever_transcript(tmp_path / ("%s.jsonl" % SESSAO), projeto)
