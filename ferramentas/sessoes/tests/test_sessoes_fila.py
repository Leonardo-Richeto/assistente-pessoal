"""Fila local: gravar, substituir, id inválido, última sessão do projeto, log."""
from __future__ import annotations

import json
import os

import pytest

import fila

RAIZ = os.path.join(os.sep, "repos", "p")


def _r(sessao, fim, raiz=RAIZ, maquina="maquina-teste", **extra):
    base = {"sessao": sessao, "projeto": os.path.basename(raiz), "raiz": raiz, "maquina": maquina, "fim": fim,
            "titulo": "t %s" % (sessao,), "arquivos": [], "comandos": [], "passagem": False}
    base.update(extra)
    return base


def _pendentes(estado, raiz=RAIZ):
    return estado / "pendentes" / fila.chave_projeto(raiz)


def test_gravar_cria_pendente_na_pasta_do_projeto(estado):
    caminho = fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00"))
    assert caminho == os.path.join(str(_pendentes(estado)), "sessao-01.json")
    with open(caminho, encoding="utf-8") as f:
        assert json.load(f)["sessao"] == "sessao-01"
    assert not [n for n in os.listdir(_pendentes(estado)) if n.startswith(".tmp")]


def test_chave_projeto_e_hash_da_raiz():
    assert len(fila.chave_projeto(RAIZ)) == 12
    assert fila.chave_projeto(RAIZ) == fila.chave_projeto(RAIZ + os.sep)
    assert fila.chave_projeto(RAIZ) != fila.chave_projeto(os.path.join(os.sep, "outro", "p"))


def test_mesma_sessao_substitui(estado):
    fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00", titulo="primeira"))
    fila.gravar(_r("sessao-01", "2026-10-20T11:00:00+00:00", titulo="retomada"))
    assert os.listdir(_pendentes(estado)) == ["sessao-01.json"]
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["titulo"] == "retomada"


def test_sessao_retomada_noutro_projeto_nao_duplica(estado):
    outra = os.path.join(os.sep, "repos", "q")
    fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00"))
    fila.gravar(_r("sessao-01", "2026-10-20T11:00:00+00:00", raiz=outra))
    assert os.listdir(_pendentes(estado)) == []
    assert os.listdir(_pendentes(estado, outra)) == ["sessao-01.json"]


@pytest.mark.parametrize("ruim", [
    "../fora", "a/b", "", "x" * 81, "com espaço", None, 123, "a.json",
    "abcdefgh\n",  # `$` do re casava antes da quebra de linha
    "curto", "CON", "nul", "COM1", "lpt9",  # curtos e nomes reservados do Windows
])
def test_id_invalido_recusado(estado, ruim):
    assert fila.id_valido(ruim) is False
    with pytest.raises(ValueError):
        fila.gravar(_r(ruim, "2026-10-20T10:00:00+00:00"))


def test_id_valido():
    assert fila.id_valido("11111111-2222-4333-8444-555555555555")
    assert fila.id_valido("abcdefgh")


def test_resumo_sem_raiz_recusado(estado):
    with pytest.raises(ValueError):
        fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00", raiz=""))


def test_marcar_enviada_e_regravar(estado):
    fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00"))
    fila.marcar_enviada("sessao-01")
    assert os.listdir(_pendentes(estado)) == []
    assert os.listdir(estado / "enviadas" / fila.chave_projeto(RAIZ)) == ["sessao-01.json"]
    fila.gravar(_r("sessao-01", "2026-10-20T12:00:00+00:00", titulo="de novo"))
    assert os.listdir(_pendentes(estado)) == ["sessao-01.json"]
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["titulo"] == "de novo"


def test_marcar_enviada_inexistente(estado):
    with pytest.raises(FileNotFoundError):
        fila.marcar_enviada("nao-existe-1")


def test_ultima_ignora_atual_outra_maquina_outro_projeto_e_vazia(estado):
    fila.gravar(_r("antiga-01", "2026-10-20T08:00:00+00:00"))
    fila.gravar(_r("anterior-1", "2026-10-20T09:00:00+00:00"))
    fila.marcar_enviada("anterior-1")
    fila.gravar(_r("outra-maquina", "2026-10-20T10:00:00+00:00", maquina="i7"))
    fila.gravar(_r("outro-projeto", "2026-10-20T10:30:00+00:00", raiz=os.path.join(os.sep, "repos", "q")))
    fila.gravar(_r("vazia-001", "2026-10-20T10:45:00+00:00", titulo=""))
    fila.gravar(_r("atual-001", "2026-10-20T11:00:00+00:00"))
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste", "atual-001")["sessao"] == "anterior-1"
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste", "atual-001", ignorar_vazias=False)["sessao"] == "vazia-001"
    assert fila.ultima_do_projeto(RAIZ, "i7", "atual-001")["sessao"] == "outra-maquina"
    assert fila.ultima_do_projeto(os.path.join(os.sep, "nenhum"), "maquina-teste") is None


def test_mesmo_nome_de_pasta_em_raizes_diferentes_nao_se_misturam(estado):
    """Achado 10: `~/a/projeto` e `~/b/projeto` têm o mesmo nome e são projetos diferentes."""
    a = os.path.join(os.sep, "a", "projeto")
    b = os.path.join(os.sep, "b", "projeto")
    fila.gravar(_r("sessao-aa", "2026-10-20T10:00:00+00:00", raiz=a))
    fila.gravar(_r("sessao-bb", "2026-10-20T11:00:00+00:00", raiz=b))
    assert fila.ultima_do_projeto(a, "maquina-teste")["sessao"] == "sessao-aa"
    assert fila.ultima_do_projeto(b, "maquina-teste")["sessao"] == "sessao-bb"


def test_corte_de_500_vale_por_projeto(estado, monkeypatch):
    """Muitas sessões de outro projeto não escondem a deste."""
    monkeypatch.setattr(fila, "MAX_ARQUIVOS_LIDOS", 3)
    fila.gravar(_r("minha-001", "2026-10-20T08:00:00+00:00"))
    outra = os.path.join(os.sep, "repos", "barulhento")
    for i in range(10):
        fila.gravar(_r("outra-%04d" % i, "2026-10-20T09:00:00+00:00", raiz=outra))
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["sessao"] == "minha-001"


def test_le_formato_antigo_sem_subpasta(estado):
    (estado / "pendentes").mkdir(parents=True)
    (estado / "enviadas").mkdir(parents=True)
    (estado / "pendentes" / "antiga-01.json").write_text(json.dumps(_r("antiga-01", "2026-10-20T08:00:00+00:00")))
    (estado / "enviadas" / "antiga-02.json").write_text(json.dumps(_r("antiga-02", "2026-10-20T09:00:00+00:00")))
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["sessao"] == "antiga-02"
    # A sessão regravada sai do formato antigo para a subpasta, sem duplicar.
    fila.gravar(_r("antiga-01", "2026-10-20T10:00:00+00:00"))
    assert not (estado / "pendentes" / "antiga-01.json").exists()
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["sessao"] == "antiga-01"
    fila.marcar_enviada("antiga-01")
    assert (estado / "enviadas" / fila.chave_projeto(RAIZ) / "antiga-01.json").exists()


def test_surrogate_solto_nao_derruba_a_gravacao(estado):
    """Achado 12: "\\ud83d" sozinho (emoji cortado) quebrava o encode em UTF-8."""
    caminho = fila.gravar(_r("sessao-01", "2026-10-20T10:00:00+00:00", titulo="emoji cortado \ud83d"))
    with open(caminho, encoding="utf-8") as f:
        assert json.load(f)["titulo"] == "emoji cortado \ud83d"


def test_ultima_sem_pasta(estado):
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste") is None


def test_arquivo_quebrado_na_fila_e_ignorado(estado):
    fila.gravar(_r("boa-0001", "2026-10-20T08:00:00+00:00"))
    (_pendentes(estado) / "ruim-0001.json").write_text("{quebrado")
    assert fila.ultima_do_projeto(RAIZ, "maquina-teste")["sessao"] == "boa-0001"


def test_log_com_data_e_corte(estado, monkeypatch):
    fila.log("primeira linha")
    texto = (estado / "hooks.log").read_text(encoding="utf-8")
    assert texto.endswith("primeira linha\n") and texto[:2] == "20"
    monkeypatch.setattr(fila, "LIMITE_LOG", 1000)
    monkeypatch.setattr(fila, "MANTER_LOG", 400)
    for i in range(100):
        fila.log("linha %03d" % i)
    texto = (estado / "hooks.log").read_text(encoding="utf-8")
    assert os.path.getsize(estado / "hooks.log") <= 1000
    assert texto.rstrip().endswith("linha 099")
    assert "primeira linha" not in texto


def test_pasta_padrao(monkeypatch, tmp_path):
    monkeypatch.delenv("ASSISTENTE_SESSOES_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name != "nt":
        assert fila.pasta_estado() == os.path.join(str(tmp_path), ".local", "state", "assistente", "sessoes")
