"""Contrato do texto do Projeto "Assistente" (ficha 1, docs/regras-de-negocio.md) com o servidor (Passo 8e).

O texto não roda no pytest. O que dá para testar: todo nome de ferramenta citado nele existe no app e não está
bloqueado. O app é o de verdade (criar_app) com as peças falsas de test_bloqueadas.py (nomes reais da versão
fixada), vault e Paperless montados.
"""

import re
import typing
from pathlib import Path

from fastmcp import Client

from assistente import banco, servidor
from test_bloqueadas import app  # noqa: F401 (fixture)

FICHAS = Path(__file__).parent.parent.parent / "docs" / "regras-de-negocio.md"
TITULO = "### Texto proposto (colar no Projeto)"
# Palavra minúscula com `_` no meio: é como o texto escreve nome de ferramenta.
NOME = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
# Citados no texto com `_` que não são ferramenta, cada um conferido abaixo no lugar certo.
NAO_FERRAMENTA = {
    "nota_vault",  # parâmetro das registrar_* e campo das consultas
    "pausa_inicio", "pausa_fim",  # valores do tipo de registrar_ponto
}


def _texto_do_projeto() -> str:
    fichas = FICHAS.read_text(encoding="utf-8")
    depois = fichas[fichas.index(TITULO) + len(TITULO):]
    return depois.split("```")[1]  # o primeiro bloco de código depois do título


def _citados() -> set[str]:
    return set(NOME.findall(_texto_do_projeto()))


def test_texto_do_projeto_foi_achado():
    texto = _texto_do_projeto()
    assert texto.lstrip("\n").startswith("Você é o assistente pessoal")
    assert "## O que nunca fazer" in texto


def test_nomes_que_nao_sao_ferramenta_existem_onde_o_texto_diz():
    citados = _citados()
    assert NAO_FERRAMENTA <= citados, "Tire de NAO_FERRAMENTA o que o texto não cita mais"
    assert {"pausa_inicio", "pausa_fim"} <= set(typing.get_args(banco.TipoPonto))


async def test_toda_ferramenta_citada_existe_e_nao_esta_bloqueada(app):  # noqa: F811
    async with Client(app) as c:
        ferramentas = {t.name: t for t in await c.list_tools()}
    citadas = _citados() - NAO_FERRAMENTA
    assert len(citadas) >= 39  # 14 do banco, 22 do vault (7 nossas e 15 do mcpvault) e 3 do Paperless
    faltando = sorted(citadas - ferramentas.keys())
    assert not faltando, f"O texto do Projeto cita ferramenta que o app não tem: {faltando}"
    assert not citadas & servidor.BLOQUEADAS
    for nome in ("registrar_gasto", "registrar_ponto", "registrar_atividade"):
        assert "nota_vault" in ferramentas[nome].input_schema["properties"], nome


async def test_texto_cita_toda_ferramenta_do_banco_e_do_vault(app):  # noqa: F811
    """O texto lista as ferramentas do banco e do vault pelo nome. Ferramenta nova: proponha a linha na ficha 1."""
    async with Client(app) as c:
        visiveis = {t.name for t in await c.list_tools()}
    do_banco_e_vault = {n for n in visiveis if not n.startswith("paperless_")}
    nao_citadas = sorted(do_banco_e_vault - _citados())
    assert not nao_citadas, f"Ferramentas fora do texto do Projeto: {nao_citadas}"


async def test_nao_ha_ferramenta_de_apagar_ou_mover_nota(app):  # noqa: F811
    """O texto diz "Não há ferramenta para apagar ou mover nota": nenhuma visível do vault apaga ou move."""
    async with Client(app) as c:
        visiveis = {t.name for t in await c.list_tools()}
    assert not {n for n in visiveis if n.startswith("vault_") and re.search(r"delete|move|rename", n)}
