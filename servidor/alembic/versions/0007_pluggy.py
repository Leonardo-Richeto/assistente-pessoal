"""pluggy: conferência dos gastos do banco e tabela das sincronizações

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26

Escrita à mão (Ficha 10, PLANO 3.3). Aditiva:
- `gastos` ganha `conferido` (padrão verdadeiro: todo gasto que já existe é manual e nasce conferido),
  `duplicata_de` (id do gasto que o do banco parece repetir; só aviso) e `previsto` (parcela futura lançada antes de
  o banco trazê-la; padrão falso). Os GRANTs de `gastos` não mudam:
  o usuário de escrita já tem UPDATE na tabela, e `conferir_gastos` muda `categoria` e `conferido`.
- `sincronizacoes`: uma linha por rodada de worker, para o aviso de falha do `contexto_inicial`.

GRANTs explícitos de `sincronizacoes`. Os privilégios padrão do 01-papeis.sh dariam UPDATE ao usuário de
escrita; aqui ele só insere (como em `chamadas` e `sessoes`):
- assistente_escrita: SELECT e INSERT na tabela; USAGE e SELECT na sequência do id. Nada de UPDATE nem DELETE.
- assistente_leitura: só SELECT na tabela.

Downgrade não apaga nada (como a 0003, a 0005 e a 0006): colunas, tabela e GRANTs ficam, sem uso pelo código
da 0006. Como não olha o banco, roda também em modo --sql. Subir de novo reaproveita o que ficou.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELA = "sincronizacoes"


def _inspetor():
    if op.get_context().as_sql:  # modo --sql (offline): não há banco para olhar
        return None
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspetor = _inspetor()
    colunas = set() if inspetor is None else {c["name"] for c in inspetor.get_columns("gastos")}
    if "conferido" not in colunas:
        op.add_column("gastos", sa.Column("conferido", sa.Boolean(), server_default="true", nullable=False))
    if "duplicata_de" not in colunas:
        op.add_column("gastos", sa.Column("duplicata_de", sa.Integer(), nullable=True))
    if "previsto" not in colunas:
        op.add_column("gastos", sa.Column("previsto", sa.Boolean(), server_default="false", nullable=False))

    if inspetor is None or not inspetor.has_table(TABELA):
        op.create_table(
            TABELA,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("worker", sa.String(length=30), nullable=False),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ok", sa.Boolean(), nullable=False),
            sa.Column("novos", sa.Integer(), nullable=False),
            sa.Column("erro", sa.String(length=300), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sincronizacoes_worker_inicio", TABELA, ["worker", "inicio"])

    if op.get_context().dialect.name == "postgresql":
        op.execute(f"REVOKE ALL ON TABLE {TABELA} FROM assistente_escrita, assistente_leitura")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABELA}_id_seq FROM assistente_escrita, assistente_leitura")
        op.execute(f"GRANT SELECT, INSERT ON TABLE {TABELA} TO assistente_escrita")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABELA}_id_seq TO assistente_escrita")
        op.execute(f"GRANT SELECT ON TABLE {TABELA} TO assistente_leitura")


def downgrade() -> None:
    # De propósito, nada: apagar a tabela ou as colunas apagaria o histórico e as conferências.
    pass
