"""auditoria: registro_id pode ficar vazio (linhas do vault, do Paperless e das negadas)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Escrita à mão (Passo 8b). Só afrouxa uma restrição: nenhum dado muda na subida.
Os GRANTs da tabela não mudam (ALTER COLUMN mantém os privilégios): o usuário de escrita
continua só com SELECT e INSERT (o UPDATE saiu na 0001); o de leitura, com SELECT.

Downgrade recusado se houver linha com registro_id vazio, e em modo --sql (offline): sem banco,
não há como contar (como a 0004; Passo 8e).
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
    # Nada é apagado nem reescrito na auditoria: se já há linhas sem registro (vault, Paperless,
    # negadas), voltar a NOT NULL exigiria inventar um valor. Nesse caso a descida é recusada.
    if op.get_context().as_sql:
        # Modo --sql (offline): não há banco para contar; gerar o SET NOT NULL às cegas falharia ou esconderia o caso.
        raise RuntimeError("Downgrade da 0002 não roda em modo --sql: precisa conferir no banco se há registro_id vazio.")
    ligacao = op.get_bind()
    sem_registro = ligacao.execute(sa.text("SELECT COUNT(*) FROM auditoria WHERE registro_id IS NULL")).scalar()
    if sem_registro:
        raise RuntimeError(
            f"Downgrade da 0002 recusado: {sem_registro} linha(s) de auditoria com registro_id vazio. "
            "A auditoria não é apagada nem reescrita; mantenha a 0002 ou trate essas linhas à mão.")
    with op.batch_alter_table("auditoria") as t:
        t.alter_column("registro_id", existing_type=sa.Integer(), nullable=False)
