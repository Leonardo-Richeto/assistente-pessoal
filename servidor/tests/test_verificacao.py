"""Verificação usada pelo scripts/verificar.sh: consulta só lê e não grava nada."""

import http.server
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select, text

from assistente import verificacao
from assistente.config import config
from assistente.modelos import Auditoria, Base, Chamada, Gasto

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def url(tmp_path):
    url = f"sqlite:///{tmp_path / 'verifica.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    _versao(engine, verificacao.cabeca_das_migracoes())
    return url


def _versao(engine, versao):
    with engine.begin() as cx:
        cx.execute(text("create table if not exists alembic_version (version_num varchar(32) not null)"))
        cx.execute(text("delete from alembic_version"))
        cx.execute(text("insert into alembic_version values (:v)"), {"v": versao})


@pytest.fixture
def ambiente(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL_LEITURA", url)
    monkeypatch.setenv("DATABASE_URL_ESCRITA", url)
    config.cache_clear()
    yield
    config.cache_clear()


def _contagens(url):
    with create_engine(url).connect() as cx:
        return [cx.execute(select(func.count()).select_from(m)).scalar() for m in (Gasto, Auditoria, Chamada)]


async def test_consulta_leitura_nao_grava(url):
    antes = _contagens(url)
    dados = await verificacao.consulta_leitura(url, TZ)
    assert dados["total"] == "0"
    assert _contagens(url) == antes == [0, 0, 0]


def test_main_sem_http_passa(ambiente, url, capsys):
    assert verificacao.main(["--sem-http"]) == 0
    assert "ok    consulta de leitura pelo MCP" in capsys.readouterr().out
    assert _contagens(url) == [0, 0, 0]


def test_main_falha_sem_banco(monkeypatch, tmp_path, capsys):
    vazio = f"sqlite:///{tmp_path / 'sem-tabelas.db'}"  # nem alembic_version existe
    monkeypatch.setenv("DATABASE_URL_LEITURA", vazio)
    monkeypatch.setenv("DATABASE_URL_ESCRITA", vazio)
    config.cache_clear()
    try:
        assert verificacao.main(["--sem-http"]) == 1
    finally:
        config.cache_clear()
    assert "FALHA consulta de leitura pelo MCP" in capsys.readouterr().out


class _Respostas(http.server.BaseHTTPRequestHandler):
    codigos: dict[str, int] = {}

    def do_GET(self):  # noqa: N802 (nome do http.server)
        self.send_response(self.codigos.get(self.path, 404))
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def http_local(monkeypatch):
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _Respostas)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("PORTA", str(servidor.server_port))
    yield _Respostas
    servidor.shutdown()


def test_http_com_login_ligado_passa(ambiente, http_local, capsys):
    http_local.codigos = {"/mcp": 401, "/.well-known/oauth-protected-resource/mcp": 200}
    config.cache_clear()
    assert verificacao.main([]) == 0
    assert "GET /mcp sem token = 401" in capsys.readouterr().out


def test_http_sem_login_falha(ambiente, http_local, capsys):
    """/mcp respondendo 200 sem token é o pior caso: login desligado. Tem de falhar."""
    http_local.codigos = {"/mcp": 200, "/.well-known/oauth-protected-resource/mcp": 404}
    config.cache_clear()
    assert verificacao.main([]) == 1
    saida = capsys.readouterr().out
    assert "FALHA GET /mcp sem token = 200 (esperado 401)" in saida


# ---------------- migração e tabelas novas ----------------

def test_cabeca_das_migracoes_e_a_0006_ou_mais_nova():
    assert verificacao.cabeca_das_migracoes() >= "0006"


def test_migracao_na_cabeca_ok(url):
    assert verificacao.checar_migracao(url) == [("ok", f"migração do banco na cabeça ({verificacao.cabeca_das_migracoes()})")]


def test_migracao_velha_falha(url):
    _versao(create_engine(url), "0004")
    [(nivel, texto)] = verificacao.checar_migracao(url)
    assert nivel == "FALHA"
    assert texto == f"banco na 0004, código espera {verificacao.cabeca_das_migracoes()}: rode as migrações"


def test_migracao_sem_alembic_version_falha(tmp_path):
    [(nivel, _)] = verificacao.checar_migracao(f"sqlite:///{tmp_path / 'x.db'}")
    assert nivel == "FALHA"


def test_main_com_banco_velho_sai_1(ambiente, url, capsys):
    _versao(create_engine(url), "0004")
    assert verificacao.main(["--sem-http"]) == 1
    assert "FALHA banco na 0004" in capsys.readouterr().out


def test_tabelas_novas_ok(url):
    assert [n for n, _ in verificacao.checar_tabelas_novas(url)] == ["ok", "ok"]


def test_tabela_nova_ausente_falha(tmp_path):
    u = f"sqlite:///{tmp_path / 'a.db'}"
    with create_engine(u).begin() as cx:
        cx.execute(text("create table sessoes (id integer)"))
    linhas = verificacao.checar_tabelas_novas(u)
    assert linhas[0][0] == "FALHA" and "notas_desatualizadas" in linhas[0][1]
    assert linhas[1][0] == "ok"


# ---------------- vault ----------------

FIXTURE = Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture
def vault(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(FIXTURE, destino)
    return destino


def _git_init(raiz):
    subprocess.run(["git", "init", "-q", str(raiz)], check=True)


def _niveis(linhas):
    return [n for n, _ in linhas]


def _textos(linhas, nivel):
    return [t for n, t in linhas if n == nivel]


def test_vault_desligado():
    assert verificacao.checar_vault("") == [("ok", "vault desligado")]


def test_vault_pasta_inexistente_falha(tmp_path):
    [(nivel, texto)] = verificacao.checar_vault(str(tmp_path / "nao-existe"))
    assert nivel == "FALHA" and "não existe" in texto


@pytest.mark.skipif(os.geteuid() == 0, reason="root lê tudo")
def test_vault_ilegivel_falha(vault):
    vault.chmod(0)
    try:
        assert _niveis(verificacao.checar_vault(str(vault))) == ["FALHA"]
    finally:
        vault.chmod(0o755)


def test_vault_conta_notas_e_avisa_sem_git(vault):
    linhas = verificacao.checar_vault(str(vault))
    assert linhas[0][0] == "ok"
    assert linhas[0][1].startswith("vault: ") and " notas indexadas em " in linhas[0][1]
    assert int(linhas[0][1].split()[1]) > 0
    assert ("AVISO", "vault sem histórico (commit por escrita desligado)") in linhas
    assert "FALHA" not in _niveis(linhas)


def test_vault_vazio_avisa_zero_notas(tmp_path):
    linhas = verificacao.checar_vault(str(tmp_path))
    assert linhas[0][0] == "AVISO" and "0 notas indexadas" in linhas[0][1]


def test_vault_com_git_gravavel_ok(vault):
    _git_init(vault)
    linhas = verificacao.checar_vault(str(vault))
    assert ("ok", "vault: .git gravável") in linhas
    assert _niveis(linhas).count("AVISO") == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root escreve em tudo")
def test_vault_git_sem_escrita_avisa(vault):
    _git_init(vault)
    (vault / ".git" / "objects").chmod(0o555)
    try:
        linhas = verificacao.checar_vault(str(vault))
    finally:
        (vault / ".git" / "objects").chmod(0o755)
    [aviso] = _textos(linhas, "AVISO")
    assert ".git/objects" in aviso and "docs/IMPLANTACAO.md B11" in aviso
    assert "FALHA" not in _niveis(linhas)


def test_vault_lock_velho_avisa_e_recente_nao(vault):
    _git_init(vault)
    lock = vault / ".git" / "index.lock"
    lock.write_text("")
    assert _textos(verificacao.checar_vault(str(vault)), "AVISO") == []
    velho = time.time() - 11 * 60
    os.utime(lock, (velho, velho))
    [aviso] = _textos(verificacao.checar_vault(str(vault)), "AVISO")
    assert "index.lock" in aviso and "11 min" in aviso


def test_vault_gitattributes_com_filtro_avisa(vault):
    (vault / ".gitattributes").write_text("# nada\n*.md filter=lfs diff=lfs\n")
    linhas = verificacao.checar_vault(str(vault))
    assert any(".gitattributes usa filter=" in t and "desligado para esses arquivos" in t for t in _textos(linhas, "AVISO"))


def test_vault_gitattributes_sem_filtro_nao_avisa(vault):
    (vault / ".gitattributes").write_text("*.md text eol=lf\n# filter=x\n")
    assert not any("gitattributes" in t for t in _textos(verificacao.checar_vault(str(vault)), "AVISO"))


# ---------------- main ----------------

def test_main_com_vault_imprime_e_aviso_nao_muda_saida(ambiente, vault, monkeypatch, capsys):
    monkeypatch.setenv("VAULT_PATH", str(vault))
    config.cache_clear()
    assert verificacao.main(["--sem-http"]) == 0  # vault sem .git = AVISO
    saida = capsys.readouterr().out
    assert "ok    migração do banco na cabeça" in saida
    assert "ok    tabela sessoes legível" in saida
    assert "AVISO vault sem histórico" in saida


def test_main_vault_inexistente_sai_1(ambiente, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "x"))
    config.cache_clear()
    assert verificacao.main(["--sem-http"]) == 1
    assert "FALHA vault:" in capsys.readouterr().out


def test_sem_banco_nao_exige_variaveis_de_banco(vault, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL_LEITURA", raising=False)
    monkeypatch.delenv("DATABASE_URL_ESCRITA", raising=False)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.chdir(vault)  # sem .env por perto
    config.cache_clear()
    assert verificacao.main(["--sem-banco", "--sem-http"]) == 0
    saida = capsys.readouterr().out
    assert "notas indexadas" in saida and "consulta de leitura" not in saida and "migração" not in saida
