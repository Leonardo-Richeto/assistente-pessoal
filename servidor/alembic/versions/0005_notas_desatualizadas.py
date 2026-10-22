"""notas_desatualizadas: marca de nota do vault que parece velha ou errada

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

Escrita à mão (Sprint 2b, Passo 8; ficha 5, regra 8). Aditiva: cria a tabela `notas_desatualizadas`;
nenhuma tabela existente muda.

Índice único parcial no caminho, só das marcas em vigor (`NOT desfeito`): uma marca em vigor por nota,
mesmo com duas chamadas ao mesmo tempo. Desfeita a marca, a nota pode ser marcada de novo.

GRANTs explícitos. Os privilégios padrão do 01-papeis.sh dariam UPDATE em todas as colunas ao usuário
de escrita; aqui ele só muda `desfeito` (o desfazer), nunca o caminho, o motivo nem o autor:
- assistente_escrita: SELECT e INSERT na tabela; UPDATE só da coluna `desfeito`; USAGE e SELECT na
  sequência do id. Nada de DELETE.
- assistente_leitura: só SELECT na tabela; nada na sequência.

Downgrade não apaga nada (como a 0003): a tabela, as marcas e os GRANTs ficam no banco, sem uso pelo
código da 0004. Como não olha o banco, roda também em modo --sql. Subir de novo reaproveita a tabela
que ficou (e repete os GRANTs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELA = "notas_desatualizadas"


def _existe(tabela: str) -> bool:
    if op.get_context().as_sql:  # modo --sql (offline): não há banco para olhar
        return False
    return sa.inspect(op.get_bind()).has_table(tabela)


def upgrade() -> None:
    if not _existe(TABELA):
        op.create_table(
            TABELA,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("caminho", sa.String(length=300), nullable=False),
            sa.Column("motivo", sa.Text(), nullable=False),
            sa.Column("autor", sa.String(length=80), nullable=True),
            sa.Column("desfeito", sa.Boolean(), server_default="false", nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_notas_desatualizadas_caminho_em_vigor", TABELA, ["caminho"], unique=True,
                        postgresql_where=sa.text("NOT desfeito"), sqlite_where=sa.text("NOT desfeito"))

    if op.get_context().dialect.name == "postgresql":
        # Primeiro tira tudo (inclusive o UPDATE de tabela dos privilégios padrão; o REVOKE de tabela leva
        # junto os de coluna), depois dá só o necessário.
        op.execute(f"REVOKE ALL ON TABLE {TABELA} FROM assistente_escrita, assistente_leitura")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABELA}_id_seq FROM assistente_escrita, assistente_leitura")
        op.execute(f"GRANT SELECT, INSERT ON TABLE {TABELA} TO assistente_escrita")
        op.execute(f"GRANT UPDATE (desfeito) ON TABLE {TABELA} TO assistente_escrita")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABELA}_id_seq TO assistente_escrita")
        op.execute(f"GRANT SELECT ON TABLE {TABELA} TO assistente_leitura")


def downgrade() -> None:
    # De propósito, nada: apagar a tabela apagaria as marcas e o histórico do desfazer.
    pass
