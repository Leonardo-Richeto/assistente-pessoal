"""gastos, ponto e atividades: coluna nota_vault (caminho da nota do vault ligada ao registro)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17

Escrita à mão (Passo 8c). Aditiva: só ADD COLUMN, nula e sem padrão; nenhuma linha muda na subida.
Os GRANTs não mudam: privilégio de tabela vale para a coluna nova (escrita: SELECT, INSERT e UPDATE,
que `vincular_nota` usa; leitura: SELECT).

Downgrade não apaga dado: se algum registro tem nota_vault preenchida, a descida é recusada (como a
0002). Sem nenhum valor, a coluna sai sem perda. No Postgres, as 3 tabelas ficam travadas da contagem
até o fim da transação. Em modo --sql (offline) a descida é recusada: sem banco, não há como contar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELAS = ("gastos", "ponto", "atividades")


def upgrade() -> None:
    for tabela in TABELAS:
        op.add_column(tabela, sa.Column("nota_vault", sa.String(length=300), nullable=True))


def downgrade() -> None:
    contexto = op.get_context()
    if contexto.as_sql:
        # Modo --sql (offline): não há banco para contar os vínculos; descer sem contar poderia apagar caminhos.
        raise RuntimeError("Downgrade da 0004 não roda em modo --sql: precisa conferir no banco se há nota_vault.")
    ligacao = op.get_bind()
    if contexto.dialect.name == "postgresql":
        # Ninguém grava nota_vault entre a contagem e o DROP COLUMN (fica até o fim da transação da migração).
        op.execute("LOCK TABLE gastos, ponto, atividades IN ACCESS EXCLUSIVE MODE")
    com_nota = {t: ligacao.execute(sa.text(f"SELECT COUNT(*) FROM {t} WHERE nota_vault IS NOT NULL")).scalar()
                for t in TABELAS}
    if any(com_nota.values()):
        resumo = ", ".join(f"{t}: {n}" for t, n in com_nota.items() if n)
        raise RuntimeError(
            f"Downgrade da 0004 recusado: há registros com nota_vault preenchida ({resumo}). "
            "O vínculo não é apagado; mantenha a 0004 ou trate essas linhas à mão.")
    for tabela in TABELAS:
        # batch: no SQLite (testes) recria a tabela; no Postgres vira um DROP COLUMN simples.
        with op.batch_alter_table(tabela) as t:
            t.drop_column("nota_vault")
