"""Envio da fila local para a tabela `sessoes` (enviar.py; Sprint 2b, Passo 11).

O ponta a ponta roda o `enviar.py` com o `/usr/bin/python3` (3.9) e `--comando` apontando para o importador de
verdade (`python -m assistente.sessoes importar`) contra um SQLite temporário. Precisa do
pacote do servidor: rode a suíte de `servidor/` (`PYTHONPATH=. uv run pytest -q ../ferramentas/sessoes/tests`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sqlite3
import subprocess
import sys

import pytest

import enviar
import fila
from conftest import PASTA_SESSOES

PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
SERVIDOR = os.path.join(os.path.dirname(os.path.dirname(PASTA_SESSOES)), "servidor")
TEM_SERVIDOR = importlib.util.find_spec("assistente") is not None and importlib.util.find_spec("sqlalchemy") is not None
ENVIAR = os.path.join(PASTA_SESSOES, "enviar.py")


def _resumo(sessao, raiz="/repos/p", fim="2026-10-20T13:00:00+00:00", **extra):
    base = {"sessao": sessao, "projeto": os.path.basename(raiz), "raiz": raiz, "maquina": "maquina-teste",
            "inicio": "2026-10-20T12:13:00+00:00", "fim": fim, "duracao_min": 47, "titulo": "t " + sessao,
            "arquivos": ["a.py"], "comandos": ["git status"], "commits": [], "passagem": False,
            "motivo_fim": "other", "versao_resumo": 2}
    base.update(extra)
    return base


def _nomes(estado, pasta):
    """Ids das sessões numa pasta da fila (`<sessao>.json` em pendentes; `<sessao>.<fim>.json` nas outras)."""
    base = estado / pasta
    if not base.exists():
        return set()
    return {p.name.split(".")[0] if not p.name.startswith(".") else p.stem for p in base.rglob("*.json")}


def _rodar(estado, argumentos, extra_env=None):
    env = dict(os.environ)
    env.pop("ASSISTENTE_SSH", None)
    env["ASSISTENTE_SESSOES_DIR"] = str(estado)
    env.update(extra_env or {})
    return subprocess.run([PYTHON, ENVIAR] + argumentos, capture_output=True, text=True, env=env, timeout=180)


@pytest.fixture
def banco(tmp_path):
    if not TEM_SERVIDOR:
        pytest.skip("sem o pacote do servidor (rode da pasta servidor/ com PYTHONPATH=.)")
    caminho = tmp_path / "sessoes.db"
    url = "sqlite:///%s" % caminho
    # Como o fixture `url` dos testes do servidor: as tabelas do modelo (a auditoria da migração 0001 tem now() de
    # padrão, que o SQLite não tem). A tabela sessoes da migração 0006 é conferida em servidor/tests/test_sessoes.py.
    subprocess.run([sys.executable, "-c", "from sqlalchemy import create_engine; from assistente.modelos import Base; "
                    "Base.metadata.create_all(create_engine(%r))" % url], cwd=SERVIDOR, check=True, capture_output=True,
                   env={**os.environ, "PYTHONPATH": SERVIDOR})
    return caminho, url


def _importador(url):
    """`--comando` que roda o importador local com o Python do servidor, com o banco no ambiente."""
    return {"DATABASE_URL_ESCRITA": url, "PYTHONPATH": SERVIDOR}, "%s -m assistente.sessoes importar" % shlex.quote(
        sys.executable)


def _no_banco(caminho):
    with sqlite3.connect(str(caminho)) as cx:
        sessoes = [r[0] for r in cx.execute("SELECT sessao FROM sessoes ORDER BY id")]
        auditoria = [json.loads(r[0]) for r in cx.execute(
            "SELECT dados FROM auditoria WHERE ferramenta = 'sessoes_importar' ORDER BY id")]
    return sessoes, auditoria


def test_ponta_a_ponta_aceitas_e_repetidas_vao_para_enviadas(estado, banco):
    caminho, url = banco
    fila.gravar(_resumo("sessao-aaaa-01"))
    fila.gravar(_resumo("sessao-bbbb-02", raiz="/repos/outro"))
    fila.gravar(_resumo("sessao-ruim-03", fim="2026-10-20T13:00:00"))  # sem fuso: recusada
    env, comando = _importador(url)

    r = _rodar(estado, ["--comando", comando], env)
    assert r.returncode == 0, r.stderr
    assert "Enviadas 2 de 3 (aceitas 2, repetidas 0), recusadas 1 (em recusadas/ 1)" in r.stdout
    assert _nomes(estado, "enviadas") == {"sessao-aaaa-01", "sessao-bbbb-02"}
    # A recusada sai de pendentes (não trava a fila) e guarda o motivo ao lado.
    assert _nomes(estado, "pendentes") == set() and _nomes(estado, "recusadas") == {"sessao-ruim-03"}
    recusadas = estado / "recusadas" / fila.chave_projeto("/repos/p")
    assert (recusadas / "sessao-ruim-03.sem-fim.json").exists()
    assert "fim: data sem fuso" in (recusadas / "sessao-ruim-03.sem-fim.motivo.txt").read_text(encoding="utf-8")
    # Mesma subpasta do projeto em enviadas, com o fim no nome.
    assert (estado / "enviadas" / fila.chave_projeto("/repos/outro") / "sessao-bbbb-02.20261020T130000Z.json").exists()
    sessoes, auditoria = _no_banco(caminho)
    assert sessoes == ["sessao-aaaa-01", "sessao-bbbb-02"]
    assert auditoria == [{"quantidade": 2, "repetidas": 0, "recusadas": 1, "maquinas": ["maquina-teste"]}]
    log = (estado / "hooks.log").read_text(encoding="utf-8")
    assert "enviar: recusada sessao-ruim-03: fim: data sem fuso" in log

    # Reenvio de algo que o banco já tem (a cópia voltou para pendentes): conta como repetida e sai da fila.
    fila.gravar(_resumo("sessao-aaaa-01"))
    r = _rodar(estado, ["--comando", comando], env)
    assert r.returncode == 0, r.stderr
    assert "Enviadas 1 de 1 (aceitas 0, repetidas 1), recusadas 0" in r.stdout
    assert _nomes(estado, "pendentes") == set()
    assert _no_banco(caminho)[0] == ["sessao-aaaa-01", "sessao-bbbb-02"]

    # Sessão retomada (outro fim): linha nova no banco e arquivo novo em enviadas, sem sobrescrever os outros.
    fila.gravar(_resumo("sessao-aaaa-01", fim="2026-10-20T15:00:00+00:00"))
    assert _rodar(estado, ["--comando", comando], env).returncode == 0
    assert _no_banco(caminho)[0] == ["sessao-aaaa-01", "sessao-bbbb-02", "sessao-aaaa-01"]
    assert sorted(os.listdir(estado / "enviadas" / fila.chave_projeto("/repos/p"))) == [
        "sessao-aaaa-01.20261020T130000Z-2.json", "sessao-aaaa-01.20261020T130000Z.json",
        "sessao-aaaa-01.20261020T150000Z.json"]


def test_comando_que_falha_nao_move_nada(estado, banco):
    _, url = banco
    fila.gravar(_resumo("sessao-aaaa-01"))
    env, comando = _importador("sqlite:////pasta/que/nao/existe/x.db")
    r = _rodar(estado, ["--comando", comando], env)
    assert r.returncode == 1
    assert "Falhou: o comando saiu com 2. Nada mudou na fila." in r.stderr
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"} and _nomes(estado, "enviadas") == set()
    assert "pasta/que/nao" not in (estado / "hooks.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("saida", ["", "não é json", '{"aceitas": "sessao-aaaa-01"}', "[1]"])
def test_resposta_estranha_nao_move_nada(estado, tmp_path, saida):
    fila.gravar(_resumo("sessao-aaaa-01"))
    falso = tmp_path / "falso.py"
    falso.write_text("import sys\nsys.stdin.read()\nprint(%r)\n" % saida, encoding="utf-8")
    r = _rodar(estado, ["--comando", "%s %s" % (PYTHON, falso)])
    assert r.returncode == 1
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"}


def test_comando_inexistente_nao_move_nada(estado):
    fila.gravar(_resumo("sessao-aaaa-01"))
    r = _rodar(estado, ["--comando", "/nao/existe/comando"])
    assert r.returncode == 1 and "não consegui rodar o comando" in r.stderr
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"}


def test_sem_assistente_ssh_sai_com_1(estado):
    fila.gravar(_resumo("sessao-aaaa-01"))
    r = _rodar(estado, [])
    assert r.returncode == 1
    assert r.stderr.strip() == enviar.SEM_SSH == (
        "Defina ASSISTENTE_SSH (ex.: usuario@i7). O PC do trabalho fica só com a fila local.")
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"}


@pytest.mark.parametrize("destino", ["-oProxyCommand=x", "usuario@i7;rm", "a b"])
def test_assistente_ssh_invalida_sai_com_1(estado, destino):
    fila.gravar(_resumo("sessao-aaaa-01"))
    r = _rodar(estado, [], {"ASSISTENTE_SSH": destino})
    assert r.returncode == 1 and "ASSISTENTE_SSH inválida" in r.stderr


def test_comando_padrao(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # sem ~/.ssh/assistente_sessoes
    monkeypatch.delenv("ASSISTENTE_SSH_CHAVE", raising=False)
    monkeypatch.setenv("ASSISTENTE_SSH", "leo@i7")
    assert enviar.comando_padrao() == [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "leo@i7",
        "docker compose --project-directory /srv/assistente/app exec -T servidor python -m assistente.sessoes importar"]
    monkeypatch.delenv("ASSISTENTE_SSH")
    assert enviar.comando_padrao() is None


def test_comando_padrao_com_a_chave_so_do_envio(monkeypatch, tmp_path):
    """Revisor do Passo 11: a chave do envio é outra, restrita no i7 pelo command= do authorized_keys."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ASSISTENTE_SSH_CHAVE", raising=False)
    monkeypatch.setenv("ASSISTENTE_SSH", "leo@i7")
    padrao = tmp_path / ".ssh" / "assistente_sessoes"
    padrao.parent.mkdir()
    padrao.write_text("chave falsa")
    comando = enviar.comando_padrao()
    assert comando[:9] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", str(padrao), "-o",
                           "IdentitiesOnly=yes"]
    assert comando[9] == "leo@i7"
    # A variável escolhe outra chave; ~ é expandido.
    outra = tmp_path / "outra_chave"
    outra.write_text("chave falsa")
    monkeypatch.setenv("ASSISTENTE_SSH_CHAVE", "~/outra_chave")
    assert enviar.comando_padrao()[5:7] == ["-i", str(outra)]


def test_chave_definida_que_nao_existe_sai_com_1(estado, tmp_path):
    fila.gravar(_resumo("sessao-aaaa-01"))
    r = _rodar(estado, [], {"ASSISTENTE_SSH": "leo@i7", "ASSISTENTE_SSH_CHAVE": str(tmp_path / "nao-existe")})
    assert r.returncode == 1 and "ASSISTENTE_SSH_CHAVE não aponta para um arquivo" in r.stderr
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"}


def test_nada_a_enviar_nao_roda_o_comando(estado):
    r = _rodar(estado, ["--comando", "/nao/existe/comando"])
    assert (r.returncode, r.stdout.strip()) == (0, "Nada a enviar.")


def test_timeout_nao_move_nada(estado, tmp_path, monkeypatch, capsys):
    fila.gravar(_resumo("sessao-aaaa-01"))
    monkeypatch.setattr(enviar, "TIMEOUT_S", 1)
    lento = tmp_path / "lento.py"
    lento.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    assert enviar.main(["--comando", "%s %s" % (sys.executable, lento)]) == 1
    assert "passou de 1 s" in capsys.readouterr().err
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"}


def _eco(tmp_path, aceitas, repetidas=(), recusadas=()):
    """Comando falso que lê a entrada, guarda o que recebeu e responde como o importador."""
    recebido = tmp_path / "recebido.jsonl"
    falso = tmp_path / "eco.py"
    resposta = json.dumps({"aceitas": list(aceitas), "repetidas": list(repetidas), "recusadas": list(recusadas)})
    falso.write_text("import sys\nopen(%r, 'wb').write(sys.stdin.buffer.read())\nprint(%r)\n" % (str(recebido),
                                                                                                    resposta),
                     encoding="utf-8")
    return "%s %s" % (sys.executable, falso), recebido


def test_lote_mais_antigas_primeiro_ate_o_limite(estado, tmp_path, monkeypatch):
    monkeypatch.setattr(enviar, "MAX_POR_VEZ", 3)
    for i in range(5):
        caminho = fila.gravar(_resumo("sessao-%04d-xx" % i, raiz="/repos/p%d" % (i % 2)))
        os.utime(caminho, (1_700_000_000 + (5 - i), 1_700_000_000 + (5 - i)))  # a última gravada é a mais antiga
    comando, recebido = _eco(tmp_path, ["sessao-0004-xx", "sessao-0003-xx"], ["sessao-0002-xx"])
    assert enviar.main(["--comando", comando]) == 0
    linhas = [json.loads(l) for l in recebido.read_bytes().splitlines()]
    assert [l["sessao"] for l in linhas] == ["sessao-0004-xx", "sessao-0003-xx", "sessao-0002-xx"]
    assert recebido.read_bytes().isascii()
    assert _nomes(estado, "pendentes") == {"sessao-0000-xx", "sessao-0001-xx"}
    assert "ficaram para depois 2" in (estado / "hooks.log").read_text(encoding="utf-8")


def test_so_move_o_que_foi_enviado(estado, tmp_path):
    """O importador (ou quem responde por ele) não move o que não estava no lote."""
    fila.gravar(_resumo("sessao-aaaa-01"))
    comando, _ = _eco(tmp_path, ["sessao-aaaa-01", "sessao-outra-99", "../x"])
    assert enviar.main(["--comando", comando]) == 0
    assert _nomes(estado, "enviadas") == {"sessao-aaaa-01"}


def test_arquivo_que_mudou_durante_o_envio_fica(estado, tmp_path, monkeypatch):
    caminho = fila.gravar(_resumo("sessao-aaaa-01"))
    comando, _ = _eco(tmp_path, ["sessao-aaaa-01"])
    original = enviar.subprocess.run

    def run_e_retoma(*a, **k):
        r = original(*a, **k)
        fila.gravar(_resumo("sessao-aaaa-01", fim="2026-10-20T15:00:00+00:00", titulo="retomada"))
        os.utime(caminho, (1_800_000_000, 1_800_000_000))
        return r

    monkeypatch.setattr(enviar.subprocess, "run", run_e_retoma)
    assert enviar.main(["--comando", comando]) == 0
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"} and _nomes(estado, "enviadas") == set()
    with open(caminho, encoding="utf-8") as f:
        assert json.load(f)["titulo"] == "retomada"


def test_arquivo_ruim_fica_e_vai_para_o_log(estado, tmp_path):
    fila.gravar(_resumo("sessao-aaaa-01"))
    pasta = estado / "pendentes" / "abc"
    pasta.mkdir(parents=True)
    (pasta / "quebrado-0001.json").write_text("{", encoding="utf-8")
    (pasta / "outro-nome-0002.json").write_text(json.dumps(_resumo("sessao-zzzz-09")), encoding="utf-8")
    (pasta / ".tmp-x.json").write_text("{}", encoding="utf-8")
    comando, recebido = _eco(tmp_path, ["sessao-aaaa-01"])
    assert enviar.main(["--comando", comando]) == 0
    assert [json.loads(l)["sessao"] for l in recebido.read_bytes().splitlines()] == ["sessao-aaaa-01"]
    assert _nomes(estado, "pendentes") == {"quebrado-0001", "outro-nome-0002", ".tmp-x"}
    log = (estado / "hooks.log").read_text(encoding="utf-8")
    assert "não li quebrado-0001.json" in log and "outro-nome-0002.json não é um resumo válido" in log


def test_formato_antigo_sem_subpasta_tambem_vai(estado, tmp_path):
    (estado / "pendentes").mkdir(parents=True)
    (estado / "pendentes" / "sessao-velha-01.json").write_text(json.dumps(_resumo("sessao-velha-01")),
                                                              encoding="utf-8")
    comando, _ = _eco(tmp_path, ["sessao-velha-01"])
    assert enviar.main(["--comando", comando]) == 0
    assert (estado / "enviadas" / "sessao-velha-01.20261020T130000Z.json").exists()


# --- Correções do revisor do Passo 11 ---

def test_600_recusadas_nao_impedem_a_sessao_nova_de_sair(estado, banco):
    """Antes, a recusada ficava em pendentes e voltava sempre na frente do lote (as mais antigas primeiro): com mais
    de 500, a sessão nova nunca saía."""
    caminho, url = banco
    for i in range(600):
        arquivo = fila.gravar(_resumo("ruim-%04d-xx" % i, fim="2026-10-20T13:00:00"))  # sem fuso: recusada
        os.utime(arquivo, (1_700_000_000 + i, 1_700_000_000 + i))
    fila.gravar(_resumo("sessao-nova-01"))
    env, comando = _importador(url)

    r = _rodar(estado, ["--comando", comando], env)
    assert r.returncode == 0, r.stderr
    assert "recusadas 500 (em recusadas/ 500)" in r.stdout and "ficaram para depois 101" in r.stdout
    # Só recusadas: o importador não gravou auditoria.
    assert _no_banco(caminho) == ([], [])

    r = _rodar(estado, ["--comando", comando], env)
    assert r.returncode == 0, r.stderr
    assert "Enviadas 1 de 101 (aceitas 1, repetidas 0), recusadas 100" in r.stdout
    assert _nomes(estado, "pendentes") == set() and _nomes(estado, "enviadas") == {"sessao-nova-01"}
    assert len(_nomes(estado, "recusadas")) == 600
    assert len(list((estado / "recusadas").rglob("*.motivo.txt"))) == 600
    assert _no_banco(caminho) == (["sessao-nova-01"], [
        {"quantidade": 1, "repetidas": 0, "recusadas": 100, "maquinas": ["maquina-teste"]}])


def test_recusa_adiada_pelo_limite_do_importador_fica_em_pendentes(estado, tmp_path):
    for i in range(3):
        arquivo = fila.gravar(_resumo("sessao-%04d-xx" % i))
        os.utime(arquivo, (1_700_000_000 + i, 1_700_000_000 + i))
    comando, _ = _eco(tmp_path, ["sessao-0000-xx"], recusadas=[
        {"linha": 2, "motivo": "passou de 2000 linhas por execução; esta e as seguintes ficam para a próxima",
         "adiada": True}])
    assert enviar.main(["--comando", comando]) == 0
    assert _nomes(estado, "enviadas") == {"sessao-0000-xx"}
    assert _nomes(estado, "pendentes") == {"sessao-0001-xx", "sessao-0002-xx"} and _nomes(estado, "recusadas") == set()


def test_regravada_no_meio_do_rename_volta_para_pendentes(estado, tmp_path, monkeypatch):
    """O hook regrava a sessão (retomada que terminou) depois da conferência da marca e antes do rename: o arquivo
    movido é a versão nova, que o banco não tem. Ela volta para pendentes; a próxima rodada envia."""
    caminho = fila.gravar(_resumo("sessao-aaaa-01"))
    comando, _ = _eco(tmp_path, ["sessao-aaaa-01"])
    original = fila.arquivar

    def regrava_e_arquiva(origem, *a, **k):
        fila.gravar(_resumo("sessao-aaaa-01", fim="2026-10-20T15:00:00+00:00", titulo="retomada"))
        return original(origem, *a, **k)

    monkeypatch.setattr(enviar.fila, "arquivar", regrava_e_arquiva)
    assert enviar.main(["--comando", comando]) == 0
    assert _nomes(estado, "pendentes") == {"sessao-aaaa-01"} and _nomes(estado, "enviadas") == set()
    with open(caminho, encoding="utf-8") as f:
        assert json.load(f)["titulo"] == "retomada"
    log = (estado / "hooks.log").read_text(encoding="utf-8")
    assert "foi regravada durante o envio; a versão nova voltou para pendentes" in log
    assert "mudaram no envio 1" in log

    monkeypatch.setattr(enviar.fila, "arquivar", original)
    comando, recebido = _eco(tmp_path, ["sessao-aaaa-01"])
    assert enviar.main(["--comando", comando]) == 0
    assert json.loads(recebido.read_bytes())["titulo"] == "retomada"
    assert _nomes(estado, "enviadas") == {"sessao-aaaa-01"} and _nomes(estado, "pendentes") == set()


def test_regravada_duas_vezes_no_meio_nao_sobrescreve_a_mais_nova(estado, tmp_path, monkeypatch):
    caminho = fila.gravar(_resumo("sessao-aaaa-01"))
    comando, _ = _eco(tmp_path, ["sessao-aaaa-01"])
    original = fila.arquivar

    def duas_regravacoes(origem, *a, **k):
        fila.gravar(_resumo("sessao-aaaa-01", fim="2026-10-20T15:00:00+00:00", titulo="do meio"))
        destino = original(origem, *a, **k)
        fila.gravar(_resumo("sessao-aaaa-01", fim="2026-10-20T16:00:00+00:00", titulo="a mais nova"))
        return destino

    monkeypatch.setattr(enviar.fila, "arquivar", duas_regravacoes)
    assert enviar.main(["--comando", comando]) == 0
    with open(caminho, encoding="utf-8") as f:
        assert json.load(f)["titulo"] == "a mais nova"
    assert "foi regravada duas vezes durante o envio" in (estado / "hooks.log").read_text(encoding="utf-8")


def test_marca_inclui_o_inode(estado, tmp_path):
    """Regravação atômica com o mesmo tamanho e a mesma data ainda muda a marca (o st_ino é outro)."""
    caminho = fila.gravar(_resumo("sessao-aaaa-01"))
    antes = enviar._marca(caminho)
    st = os.stat(caminho)
    fila.gravar(_resumo("sessao-aaaa-01"))
    os.utime(caminho, ns=(st.st_atime_ns, st.st_mtime_ns))
    depois = enviar._marca(caminho)
    assert antes[1:] == depois[1:] and antes != depois


def test_compila_no_python_39():
    if not os.path.exists("/usr/bin/python3"):
        pytest.skip("sem /usr/bin/python3")
    r = subprocess.run(["/usr/bin/python3", "-m", "py_compile", ENVIAR], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
