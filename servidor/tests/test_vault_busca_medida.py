"""Medida da busca (item 2b.10): leitura da tabela de perguntas, contas e opção --pesos, no vault sintético."""

import json
from pathlib import Path

import pytest

from assistente import vault_busca, vault_busca_medida

VAULT = Path(__file__).parent / "fixtures" / "vault"

PERGUNTAS = """# Perguntas

> Arquivo sintético.

| pergunta | nota esperada |
|---|---|
| adubo | 10-projetos/horta-comunitaria/decisao-compostagem.md |
| plano de estudos | 60-planos/plano-de-estudos.md |
| mutirão | 10-projetos/horta-comunitaria/horta-comunitaria.md ou 20-areas/perfil-do-leonardo.md |
| horta | 20-areas/perfil-do-leonardo.md |
| bicicleta | 00-inbox/nota-que-nao-existe.md |
"""


@pytest.fixture
def perguntas(tmp_path) -> Path:
    arquivo = tmp_path / "perguntas.md"
    arquivo.write_text(PERGUNTAS, encoding="utf-8")
    return arquivo


def test_ler_perguntas_ignora_cabecalho_e_aceita_ou(perguntas):
    lidas = vault_busca_medida.ler_perguntas(perguntas)
    assert len(lidas) == 5
    assert lidas[0] == ("adubo", ["10-projetos/horta-comunitaria/decisao-compostagem.md"])
    assert lidas[2][1] == ["10-projetos/horta-comunitaria/horta-comunitaria.md", "20-areas/perfil-do-leonardo.md"]


def test_numeros(perguntas):
    r = vault_busca_medida.medir(VAULT, vault_busca_medida.ler_perguntas(perguntas))
    assert [i["posicao"] for i in r["itens"]] == [1, 1, 2, None, None]
    assert r["erros_de_cadastro"] == 1  # a nota inexistente fica fora da conta
    assert (r["n"], r["acerto_entre_5"], r["acerto_em_1"]) == (4, 3, 2)
    assert r["mrr"] == 0.625
    assert r["ms_por_busca"] >= 0
    assert r["itens"][3]["achadas"]  # quem errou traz o que a busca achou


def test_cli_texto(perguntas, capsys):
    assert vault_busca_medida.main(["--vault", str(VAULT), "--perguntas", str(perguntas)]) == 0
    saida = capsys.readouterr().out
    assert "Acerto entre as 5: 3/4 (75%)" in saida
    assert "Acerto em 1º: 2/4" in saida
    assert "MRR: 0.625" in saida
    assert "[fora] horta" in saida
    assert "erro de cadastro" in saida and "nota-que-nao-existe.md" in saida


def test_cli_pesos_so_vale_na_execucao(perguntas, capsys):
    antes = vault_busca.PESOS
    args = ["--vault", str(VAULT), "--perguntas", str(perguntas), "--json"]
    assert vault_busca_medida.main(args + ["--pesos", "1,1,1,1,10"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["pesos"] == [1, 1, 1, 1, 10]
    assert vault_busca.PESOS == antes
    assert vault_busca_medida.main(args) == 0
    assert json.loads(capsys.readouterr().out)["pesos"] == list(antes)


def test_cli_recusa_pesos_e_arquivos_invalidos(perguntas, tmp_path, capsys):
    base = ["--vault", str(VAULT), "--perguntas", str(perguntas)]
    assert vault_busca_medida.main(base + ["--pesos", "1,2,3"]) == 2
    assert vault_busca_medida.main(base + ["--pesos", "a,b,c,d,e"]) == 2
    assert vault_busca_medida.main(["--vault", str(VAULT), "--perguntas", str(tmp_path / "nada.md")]) == 2
    assert vault_busca_medida.main(["--vault", str(tmp_path / "nao-existe")]) == 2
    capsys.readouterr()


def test_arquivo_de_perguntas_dentro_do_vault_nao_aparece_nos_resultados(tmp_path):
    import shutil
    vault = tmp_path / "v"
    shutil.copytree(VAULT, vault)
    (vault / "90-meta" / "perguntas-da-busca.md").write_text(PERGUNTAS, encoding="utf-8")
    perguntas = vault_busca_medida.ler_perguntas(vault / "90-meta" / "perguntas-da-busca.md")
    r = vault_busca_medida.medir(vault, perguntas, arquivo_perguntas="90-meta/perguntas-da-busca.md")
    assert all("perguntas-da-busca" not in c for i in r["itens"] for c in i["achadas"])
