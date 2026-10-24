"""Verificação de saúde usada por scripts/verificar.sh. Roda dentro do container do servidor.

Só lê. A consulta passa pelas ferramentas MCP do banco (cliente em memória) com o usuário de
LEITURA nos dois papéis, sem o middleware de registro: nada é gravado, nem em `chamadas`.
O HTTP local confere que o login está ligado (/mcp sem token = 401) e que o servidor resolve os
nomes de que o login depende.

    python -m assistente.verificacao            # consulta + HTTP
    python -m assistente.verificacao --sem-http # só a consulta
    python -m assistente.verificacao --sem-banco --sem-http  # só o vault (lê VAULT_PATH do ambiente)
Cada linha começa com `ok`, `AVISO` ou `FALHA`. Sai com 0 se nada falhou (AVISO não conta), 1 se algo falhou.
"""

import argparse
import asyncio
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastmcp import Client
from sqlalchemy import create_engine, text

from .banco import criar_servidor_banco
from .config import config
from .db import Bancos, opcoes_engine
from .vault_busca import IndiceVault

# O que cada caminho precisa responder sem token.
ESPERADO_HTTP = {"/mcp": 401, "/.well-known/oauth-protected-resource/mcp": 200}


async def consulta_leitura(url_leitura: str, tz: ZoneInfo) -> dict:
    """Chama `consultar_gastos` de hoje pelo MCP em memória, só com o usuário de leitura."""
    servidor = criar_servidor_banco(Bancos.de_urls(url_leitura, url_leitura), tz)
    hoje = datetime.now(tz).date().isoformat()
    async with Client(servidor) as c:
        return (await c.call_tool("consultar_gastos", {"inicio": hoje, "fim": hoje})).data


def status_http(url: str, timeout: float = 10) -> int:
    """Código HTTP de um GET sem token (erro HTTP também é resposta)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


Linha = tuple[str, str]  # (nível, texto): nível é "ok", "AVISO" ou "FALHA"

# Nomes que o login resolve a cada renovação: o cadastro do cliente do claude.ai (CIMD) e o token
# do Google. Sem DNS, o /token responde 401 e o claude.ai mostra "sign-in server unavailable"
# (2026-10-24, depois de um reboot: o Docker subiu antes do Tailscale do host escrever o resolv.conf).
NOMES_DO_LOGIN = ("claude.ai", "oauth2.googleapis.com")
_resolver = socket.getaddrinfo


def checar_dns(nomes: tuple[str, ...] = NOMES_DO_LOGIN) -> list[Linha]:
    """Resolve cada nome de que o login depende, de dentro do container."""
    falharam = []
    for nome in nomes:
        try:
            _resolver(nome, 443)
        except OSError as e:
            falharam.append(f"{nome} ({e})")
    if falharam:
        return [("FALHA", "DNS do servidor não resolve " + ", ".join(falharam)
                 + ": o login pelo claude.ai falha; veja `dns:` no docker-compose.yml")]
    return [("ok", "DNS do servidor resolve " + ", ".join(nomes))]


LOCK_VELHO_S = 600
TABELAS_NOVAS = ("notas_desatualizadas", "sessoes")


def cabeca_das_migracoes() -> str:
    """Revisão mais nova dos scripts do pacote, lida pela API do Alembic (não roda migração)."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def checar_migracao(url_leitura: str) -> list[Linha]:
    """Compara `alembic_version` do banco com a cabeça das migrações do código."""
    try:
        esperada = cabeca_das_migracoes()
        with create_engine(url_leitura, **opcoes_engine(url_leitura)).connect() as cx:
            atual = cx.execute(text("select version_num from alembic_version")).scalar()
    except Exception as e:
        return [("FALHA", f"migração do banco: {type(e).__name__}: {e}")]
    if atual == esperada:
        return [("ok", f"migração do banco na cabeça ({atual})")]
    return [("FALHA", f"banco na {atual}, código espera {esperada}: rode as migrações")]


def checar_tabelas_novas(url_leitura: str) -> list[Linha]:
    """Lê as tabelas da Fase 2b com o usuário de leitura (permissão faltando = FALHA)."""
    linhas: list[Linha] = []
    engine = create_engine(url_leitura, **opcoes_engine(url_leitura))
    for tabela in TABELAS_NOVAS:
        try:
            with engine.connect() as cx:
                cx.execute(text(f"select 1 from {tabela} limit 1")).first()
            linhas.append(("ok", f"tabela {tabela} legível pela leitura"))
        except Exception as e:
            linhas.append(("FALHA", f"tabela {tabela} não legível pela leitura: {type(e).__name__}: {str(e).splitlines()[0]}"))
    return linhas


def _gravavel(caminho: Path) -> bool:
    return os.access(caminho, os.W_OK | os.X_OK)


def checar_vault(vault_path: str, agora: float | None = None) -> list[Linha]:
    """Pasta, índice, repositório git e travas do vault. Sem `vault_path`: desligado."""
    if not vault_path:
        return [("ok", "vault desligado")]
    raiz = Path(vault_path)
    if not raiz.is_dir() or not os.access(raiz, os.R_OK | os.X_OK):
        return [("FALHA", f"vault: {raiz} não existe ou não é legível")]
    linhas: list[Linha] = []
    t0 = time.perf_counter()
    try:
        n = IndiceVault(raiz)._atual().execute("select count(*) from t").fetchone()[0]
    except Exception as e:
        return [("FALHA", f"vault: índice falhou: {type(e).__name__}: {e}")]
    ms = round((time.perf_counter() - t0) * 1000)
    linhas.append(("ok" if n else "AVISO", f"vault: {n} notas indexadas em {ms} ms"))

    git = raiz / ".git"
    if not os.path.lexists(git):
        linhas.append(("AVISO", "vault sem histórico (commit por escrita desligado)"))
    else:
        falta = [p for p in (git, git / "objects") if not _gravavel(p)]
        if falta:
            linhas.append(("AVISO", "vault: o usuário atual não escreve em "
                           + ", ".join(p.relative_to(raiz).as_posix() for p in falta)
                           + ": o commit por escrita vai falhar; veja docs/IMPLANTACAO.md B11"))
        else:
            linhas.append(("ok", "vault: .git gravável"))
        lock = git / "index.lock"
        try:
            idade = (agora or time.time()) - lock.stat().st_mtime
        except OSError:
            idade = None
        if idade is not None and idade > LOCK_VELHO_S:
            linhas.append(("AVISO", f"vault: .git/index.lock parado há {round(idade / 60)} min; apague se nenhum git roda"))
    for attr in sorted(raiz.rglob(".gitattributes")):
        if ".git" in attr.relative_to(raiz).parts[:-1]:
            continue
        try:
            filtrado = any("filter=" in ln and not ln.lstrip().startswith("#")
                           for ln in attr.read_text(errors="replace").splitlines())
        except OSError:
            continue
        if filtrado:
            linhas.append(("AVISO", f"vault: {attr.relative_to(raiz).as_posix()} usa filter=: "
                           "o commit por escrita fica desligado para esses arquivos"))
    return linhas


def imprimir(linhas: list[Linha]) -> int:
    """Imprime as linhas e devolve quantas são FALHA."""
    for nivel, texto in linhas:
        print(f"{nivel:<5} {texto}")
    return sum(1 for nivel, _ in linhas if nivel == "FALHA")


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--sem-http", action="store_true", help="não confere o HTTP local")
    args.add_argument("--sem-banco", action="store_true",
                      help="só vault (e HTTP): não lê o banco; VAULT_PATH e PORTA vêm direto do ambiente")
    opcoes = args.parse_args(argv)

    falhas = 0
    if opcoes.sem_banco:  # config() exige as URLs do banco; aqui só duas variáveis
        vault_path = os.environ.get("VAULT_PATH", "")
        porta = int(os.environ.get("PORTA", "8000"))
    else:
        cfg = config()
        vault_path, porta = cfg.vault_path, cfg.porta
        try:
            dados = asyncio.run(consulta_leitura(cfg.database_url_leitura, cfg.tz))
            print(f"ok    consulta de leitura pelo MCP (gastos de hoje: total {dados['total']})")
        except Exception as e:  # qualquer falha aqui é falha da verificação
            print(f"FALHA consulta de leitura pelo MCP: {type(e).__name__}: {e}")
            falhas += 1
        falhas += imprimir(checar_migracao(cfg.database_url_leitura))
        falhas += imprimir(checar_tabelas_novas(cfg.database_url_leitura))

    falhas += imprimir(checar_vault(vault_path))

    if not opcoes.sem_http:
        base = f"http://127.0.0.1:{porta}"
        for caminho, esperado in ESPERADO_HTTP.items():
            try:
                obtido = status_http(base + caminho)
            except Exception as e:
                print(f"FALHA GET {caminho}: {type(e).__name__}: {e}")
                falhas += 1
                continue
            if obtido == esperado:
                print(f"ok    GET {caminho} sem token = {obtido}")
            else:
                print(f"FALHA GET {caminho} sem token = {obtido} (esperado {esperado})")
                falhas += 1
        falhas += imprimir(checar_dns())

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
