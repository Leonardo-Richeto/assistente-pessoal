"""Lista das notas marcadas como desatualizadas, para o lint diário do vault (Sprint 2b, Passo 8; ficha 5, regra 8).

    python -m assistente.desatualizadas

Lê `DATABASE_URL_LEITURA` (usuário só com SELECT) e imprime uma linha por marca em vigor, a mais nova primeiro:
    - <caminho> — <motivo> (marca <id>, AAAA-MM-DD)
Sem marca, não imprime nada. Código 0; erro de banco ou variável faltando: mensagem em stderr e código 2.
O `deploy/vault/lint-diario.sh` roda isto no container `servidor` e junta a saída ao relatório.
O motivo é texto do modelo: sai numa linha só (quebras viram espaço), nunca é executado.
"""

import os
import sys
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .db import opcoes_engine
from .modelos import NotaDesatualizada

FUSO = "America/Sao_Paulo"


def _uma_linha(texto: str) -> str:
    return " ".join(texto.split())


def linhas(url: str, tz: ZoneInfo) -> list[str]:
    """As linhas da lista, uma por marca em vigor, a mais nova primeiro."""
    engine = create_engine(url, **opcoes_engine(url))
    try:
        with Session(engine) as s:
            marcas = s.scalars(select(NotaDesatualizada).where(NotaDesatualizada.desfeito.is_(False))
                               .order_by(NotaDesatualizada.id.desc())).all()
    finally:
        engine.dispose()
    saida = []
    for m in marcas:
        # O SQLite (testes) devolve sem fuso o que gravou em UTC; o Postgres devolve com fuso.
        momento = m.criado_em if m.criado_em.tzinfo else m.criado_em.replace(tzinfo=timezone.utc)
        saida.append(f"- {_uma_linha(m.caminho)} — {_uma_linha(m.motivo)} (marca {m.id}, "
                     f"{momento.astimezone(tz):%Y-%m-%d})")
    return saida


def main() -> int:
    url = os.environ.get("DATABASE_URL_LEITURA", "")
    if not url:
        print("desatualizadas: DATABASE_URL_LEITURA não definida.", file=sys.stderr)
        return 2
    try:
        resultado = linhas(url, ZoneInfo(os.environ.get("FUSO", FUSO)))
    except Exception as e:  # noqa: BLE001 (qualquer falha do banco vira código 2, sem a URL com senha)
        print(f"desatualizadas: não consegui ler as marcas ({type(e).__name__}).", file=sys.stderr)
        return 2
    for linha in resultado:
        print(linha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
