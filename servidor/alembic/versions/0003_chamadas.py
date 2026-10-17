"""chamadas: toda chamada de ferramenta, inclusive leitura, com a origem

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17

Escrita à mão (Passo 8b3). Aditiva: cria a tabela `chamadas`; nenhuma tabela existente muda.

GRANTs explícitos. Os privilégios padrão do 01-papeis.sh dariam UPDATE ao usuário de escrita;
aqui a tabela fica só de INSERT, como a `auditoria`:
- assistente_escrita: SELECT e INSERT na tabela; USAGE e SELECT na sequência do id.
- assistente_leitura: só SELECT na tabela; nada na sequência.

Downgrade não apaga nada: a tabela e os dados ficam no banco, sem uso pelo código da 0002.
Subir de novo reaproveita a tabela que ficou (e repete os GRANTs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existe(tabela: str) -> bool:
    if op.get_context().as_sql:  # modo --sql (offline): não há banco para olhar
        return False
    return sa.inspect(op.get_bind()).has_table(tabela)


def upgrade() -> None:
    if not _existe("chamadas"):
        op.create_table(
            "chamadas",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("momento", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("ferramenta", sa.String(length=60), nullable=False),
            sa.Column("resultado", sa.String(length=20), nullable=False),
            sa.Column("autor", sa.String(length=80), nullable=True),
            sa.Column("cliente", sa.String(length=80), nullable=True),
            sa.Column("versao_cliente", sa.String(length=40), nullable=True),
            sa.Column("sessao", sa.String(length=100), nullable=True),
            sa.Column("user_agent", sa.String(length=200), nullable=True),
            sa.Column("modelo_declarado", sa.String(length=60), nullable=True),
            sa.Column("duracao_ms", sa.Integer(), nullable=False),
            # Sem chave estrangeira, como `auditoria.registro_id`: a linha de `chamadas` nunca é recusada
            # por causa do vínculo.
            sa.Column("auditoria_id", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_chamadas_momento"), "chamadas", ["momento"], unique=False)

    if op.get_context().dialect.name == "postgresql":
        # Primeiro tira tudo (inclusive o UPDATE dos privilégios padrão), depois dá só o necessário.
        op.execute("REVOKE ALL ON TABLE chamadas FROM assistente_escrita, assistente_leitura")
        op.execute("REVOKE ALL ON SEQUENCE chamadas_id_seq FROM assistente_escrita, assistente_leitura")
        op.execute("GRANT SELECT, INSERT ON TABLE chamadas TO assistente_escrita")
        op.execute("GRANT USAGE, SELECT ON SEQUENCE chamadas_id_seq TO assistente_escrita")
        op.execute("GRANT SELECT ON TABLE chamadas TO assistente_leitura")


def downgrade() -> None:
    # De propósito, nada: apagar a tabela apagaria o histórico de chamadas.
    pass
