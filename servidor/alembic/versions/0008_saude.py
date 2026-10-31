"""saude: dados do app Saúde do iPhone (Apple Watch)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31

Escrita à mão (Ficha 14, PLANO 5b.1). Aditiva: cria seis tabelas; nenhuma tabela existente muda.
- `saude_importacoes`: uma linha por importação do `export.zip`, só com contagens e o bloco "Me".
- `saude_amostras`, `saude_treinos`, `saude_rotas`, `saude_aneis`, `saude_ecg`: o que veio do export. Cada uma tem
  `chave` única (sha256 dos campos que identificam o dado): reimportar não duplica.

GRANTs explícitos. Os privilégios padrão do 01-papeis.sh dariam UPDATE e DELETE ao usuário de escrita:
- assistente_escrita: SELECT e INSERT nas tabelas; USAGE e SELECT nas sequências do id. Nada de UPDATE nem DELETE
  (o `desfeito` existe para a correção da regra 4; o UPDATE dele entra com a ferramenta que corrigir). Exceção:
  UPDATE só das colunas de resultado de `saude_importacoes` (fim, ok, data_export, perfil, contagens), porque a
  importação cria a linha no começo (o id vai em cada dado) e a completa no fim, na mesma transação.
- assistente_leitura: só SELECT nas tabelas.

Downgrade não apaga nada (como a 0003, a 0005, a 0006 e a 0007): tabelas, dados e GRANTs ficam, sem uso pelo código
da 0007. Como não olha o banco, roda também em modo --sql. Subir de novo reaproveita as tabelas que ficaram.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELAS = ("saude_importacoes", "saude_amostras", "saude_treinos", "saude_rotas", "saude_aneis", "saude_ecg")


def _existe(tabela: str) -> bool:
    if op.get_context().as_sql:  # modo --sql (offline): não há banco para olhar
        return False
    return sa.inspect(op.get_bind()).has_table(tabela)


def _comuns() -> list[sa.Column]:
    """Colunas de toda tabela de dado de saúde (modelos._Saude)."""
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("chave", sa.String(length=64), nullable=False),
        sa.Column("importacao_id", sa.Integer(), nullable=True),
        sa.Column("desfeito", sa.Boolean(), server_default="false", nullable=False),
    ]


def _origem() -> list[sa.Column]:
    return [
        sa.Column("criado_no_aparelho", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origem", sa.String(length=120), nullable=False),
        sa.Column("versao_origem", sa.String(length=60), nullable=True),
        sa.Column("aparelho", sa.Text(), nullable=True),
        sa.Column("metadados", sa.JSON(), nullable=True),
    ]


def _criar(tabela: str, *colunas: sa.Column) -> None:
    op.create_table(tabela, *_comuns(), *colunas, sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("chave"))


def upgrade() -> None:
    if not _existe("saude_importacoes"):
        op.create_table(
            "saude_importacoes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ok", sa.Boolean(), nullable=False),
            sa.Column("arquivo", sa.String(length=200), nullable=False),
            sa.Column("data_export", sa.DateTime(timezone=True), nullable=True),
            sa.Column("perfil", sa.JSON(), nullable=True),
            sa.Column("contagens", sa.JSON(), nullable=False),
            sa.Column("erro", sa.String(length=300), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _existe("saude_amostras"):
        _criar(
            "saude_amostras",
            sa.Column("tipo", sa.String(length=100), nullable=False),
            sa.Column("valor", sa.Float(), nullable=True),
            sa.Column("valor_texto", sa.String(length=120), nullable=True),
            sa.Column("unidade", sa.String(length=40), nullable=True),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
            *_origem(),
            sa.Column("batidas", sa.JSON(), nullable=True),
        )
        op.create_index("ix_saude_amostras_tipo_inicio", "saude_amostras", ["tipo", "inicio"])
    if not _existe("saude_treinos"):
        _criar(
            "saude_treinos",
            sa.Column("tipo", sa.String(length=100), nullable=False),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duracao", sa.Float(), nullable=True),
            sa.Column("unidade_duracao", sa.String(length=20), nullable=True),
            *_origem(),
            sa.Column("estatisticas", sa.JSON(), nullable=False),
            sa.Column("eventos", sa.JSON(), nullable=False),
            sa.Column("zonas", sa.JSON(), nullable=False),
            sa.Column("amostras", sa.JSON(), nullable=False),
        )
        op.create_index("ix_saude_treinos_inicio", "saude_treinos", ["inicio"])
    if not _existe("saude_rotas"):
        _criar(
            "saude_rotas",
            sa.Column("treino_chave", sa.String(length=64), nullable=True),
            sa.Column("inicio", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fim", sa.DateTime(timezone=True), nullable=True),
            sa.Column("quantidade", sa.Integer(), nullable=False),
            sa.Column("pontos", sa.JSON(), nullable=False),
        )
        op.create_index("ix_saude_rotas_treino_chave", "saude_rotas", ["treino_chave"])
    if not _existe("saude_aneis"):
        _criar(
            "saude_aneis",
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("valores", sa.JSON(), nullable=False),
        )
        op.create_index("ix_saude_aneis_data", "saude_aneis", ["data"])
    if not _existe("saude_ecg"):
        _criar(
            "saude_ecg",
            sa.Column("registrado_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cabecalho", sa.JSON(), nullable=False),
            sa.Column("amostras", sa.JSON(), nullable=False),
        )

    if op.get_context().dialect.name == "postgresql":
        for tabela in TABELAS:
            # Primeiro tira tudo (inclusive UPDATE e DELETE dos privilégios padrão), depois dá só o necessário.
            op.execute(f"REVOKE ALL ON TABLE {tabela} FROM assistente_escrita, assistente_leitura")
            op.execute(f"REVOKE ALL ON SEQUENCE {tabela}_id_seq FROM assistente_escrita, assistente_leitura")
            op.execute(f"GRANT SELECT, INSERT ON TABLE {tabela} TO assistente_escrita")
            op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {tabela}_id_seq TO assistente_escrita")
            op.execute(f"GRANT SELECT ON TABLE {tabela} TO assistente_leitura")
        op.execute("GRANT UPDATE (fim, ok, data_export, perfil, contagens) ON TABLE saude_importacoes "
                   "TO assistente_escrita")


def downgrade() -> None:
    # De propósito, nada: apagar as tabelas apagaria os dados de saúde (Ficha 14, regra 4: gravou, fica).
    pass
