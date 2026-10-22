"""sessoes: resumo das sessões do Claude Code, enviado pelas máquinas

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22

Escrita à mão (Sprint 2b, Passo 11; ficha 5, regra 9). Aditiva: cria a tabela `sessoes`; nenhuma tabela
existente muda.

Só INSERT e SELECT, como `chamadas`: nada se apaga nem se altera. Sessão retomada chega de novo com outro
`fim` e vira linha nova. Índice único em (`sessao`, `fim`): o mesmo resumo não entra duas vezes (a importação
conta o repetido e segue). Índice em `fim` para a consulta por período.

GRANTs explícitos. Os privilégios padrão do 01-papeis.sh dariam UPDATE e DELETE ao usuário de escrita:
- assistente_escrita: SELECT e INSERT na tabela; USAGE e SELECT na sequência do id. Nada de UPDATE nem DELETE.
- assistente_leitura: só SELECT na tabela; nada na sequência.

Downgrade não apaga nada (como a 0003 e a 0005): a tabela, as sessões e os GRANTs ficam no banco, sem uso pelo
código da 0005. Como não olha o banco, roda também em modo --sql. Subir de novo reaproveita a tabela que ficou
(e repete os GRANTs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELA = "sessoes"


def _existe(tabela: str) -> bool:
    if op.get_context().as_sql:  # modo --sql (offline): não há banco para olhar
        return False
    return sa.inspect(op.get_bind()).has_table(tabela)


def upgrade() -> None:
    if not _existe(TABELA):
        op.create_table(
            TABELA,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("recebido_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("sessao", sa.String(length=80), nullable=False),
            sa.Column("projeto", sa.String(length=120), nullable=False),
            sa.Column("raiz", sa.String(length=300), nullable=False),
            sa.Column("maquina", sa.String(length=60), nullable=False),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duracao_min", sa.Integer(), nullable=False),
            sa.Column("titulo", sa.String(length=200), nullable=False),
            sa.Column("arquivos", sa.JSON(), nullable=False),
            sa.Column("comandos", sa.JSON(), nullable=False),
            sa.Column("commits", sa.JSON(), nullable=False),
            sa.Column("passagem", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("motivo_fim", sa.String(length=40), nullable=False),
            sa.Column("parcial", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("versao_resumo", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sessoes_sessao_fim", TABELA, ["sessao", "fim"], unique=True)
        op.create_index("ix_sessoes_fim", TABELA, ["fim"])

    if op.get_context().dialect.name == "postgresql":
        # Primeiro tira tudo (inclusive UPDATE e DELETE dos privilégios padrão), depois dá só o necessário.
        op.execute(f"REVOKE ALL ON TABLE {TABELA} FROM assistente_escrita, assistente_leitura")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABELA}_id_seq FROM assistente_escrita, assistente_leitura")
        op.execute(f"GRANT SELECT, INSERT ON TABLE {TABELA} TO assistente_escrita")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABELA}_id_seq TO assistente_escrita")
        op.execute(f"GRANT SELECT ON TABLE {TABELA} TO assistente_leitura")


def downgrade() -> None:
    # De propósito, nada: apagar a tabela apagaria as sessões (retenção: guardar tudo, ficha 5 decisão 3).
    pass
