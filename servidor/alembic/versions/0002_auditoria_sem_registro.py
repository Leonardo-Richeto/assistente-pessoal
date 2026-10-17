"""auditoria: registro_id pode ficar vazio (linhas do vault, do Paperless e das negadas)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Escrita à mão (Passo 8b). Só afrouxa uma restrição: nenhum dado muda na subida.
Os GRANTs da tabela não mudam (ALTER COLUMN mantém os privilégios): o usuário de escrita
continua só com SELECT e INSERT (o UPDATE saiu na 0001); o de leitura, com SELECT.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch: no SQLite (testes) recria a tabela; no Postgres vira um ALTER COLUMN simples.
    with op.batch_alter_table("auditoria") as t:
        t.alter_column("registro_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Nada é apagado: as linhas sem registro ficam com registro_id = 0 (nenhum registro real
    # tem id 0) e continuam identificáveis por tabela = vault | paperless | ferramenta.
    op.execute("UPDATE auditoria SET registro_id = 0 WHERE registro_id IS NULL")
    with op.batch_alter_table("auditoria") as t:
        t.alter_column("registro_id", existing_type=sa.Integer(), nullable=False)
