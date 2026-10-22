"""Modelos do banco. O banco é a fonte da verdade; a IA consulta, não "lembra".

Registros nunca são apagados: "desfazer" marca `desfeito = true` e grava auditoria.
Para um dado novo, crie o modelo aqui e gere a migração com
`alembic revision --autogenerate -m "..."`.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class _Registro:
    id: Mapped[int] = mapped_column(primary_key=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    desfeito: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Caminho relativo da nota do vault com a parte subjetiva do registro (Passo 8c, ficha 1 item 6).
    # A nota leva `registro: <tipo>-<id>` no frontmatter. O servidor não confere se a nota existe.
    nota_vault: Mapped[str | None] = mapped_column(String(300))


class Gasto(_Registro, Base):
    __tablename__ = "gastos"

    data: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    descricao: Mapped[str] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(String(60), index=True)
    forma_pagamento: Mapped[str | None] = mapped_column(String(40))
    # "manual" (pelo chat) ou o nome do worker de ingestão, ex.: "pluggy"
    origem: Mapped[str] = mapped_column(String(30), default="manual", server_default="manual")
    id_externo: Mapped[str | None] = mapped_column(String(120), unique=True)


class Ponto(_Registro, Base):
    __tablename__ = "ponto"

    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # entrada | saida | pausa_inicio | pausa_fim
    tipo: Mapped[str] = mapped_column(String(20))
    observacao: Mapped[str | None] = mapped_column(Text)


class Atividade(_Registro, Base):
    """Diário: o que ele fez no dia."""

    __tablename__ = "atividades"

    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    descricao: Mapped[str] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(200))


class NotaDesatualizada(Base):
    """Marca de nota do vault que parece velha ou errada (Passo 8, 2b.8; ficha 5, regra 8). Não mexe na nota.

    Só INSERT e UPDATE da coluna `desfeito` (migração 0005). Desfazer = `desfeito = true`, como `_Registro`.
    """

    __tablename__ = "notas_desatualizadas"
    # Uma marca em vigor por nota: o índice único parcial (só das não desfeitas) segura duas marcas
    # simultâneas da mesma nota e serve de índice do caminho nas consultas das marcas em vigor.
    __table_args__ = (
        Index("ix_notas_desatualizadas_caminho_em_vigor", "caminho", unique=True,
              postgresql_where=text("NOT desfeito"), sqlite_where=text("NOT desfeito")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Caminho relativo da nota (formato conferido por `caminho_da_nota`; o servidor não confere se existe).
    caminho: Mapped[str] = mapped_column(String(300))
    # Por que a nota parece velha ou errada, nas palavras do modelo (até 500 caracteres, conferido na ferramenta).
    motivo: Mapped[str] = mapped_column(Text)
    # Conta conferida na lista (como `Auditoria.autor`); vazio sem token.
    autor: Mapped[str | None] = mapped_column(String(80))
    desfeito: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Auditoria(Base):
    """Toda escrita feita por ferramenta passa por aqui, e toda tentativa negada (registro.py)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Nome da ferramenta; `<nome invalido>` se o nome pedido não for só letras, números e `_`.
    ferramenta: Mapped[str] = mapped_column(String(60))
    # Banco: gastos | ponto | atividades | notas_desatualizadas. Peças: vault | paperless. Outro nome: ferramenta.
    tabela: Mapped[str] = mapped_column(String(60))
    # Banco: id do gasto, ponto, atividade ou marca. Linha ok | erro | cancelado | negado depois de uma
    # `escrever`: o id dessa linha `escrever` (auditoria.id). Vazio na `escrever` e na negada sem ela.
    registro_id: Mapped[int | None]
    # Banco: criar | desfazer; vincular | desfazer_vinculo (caminho da nota, Passo 8c).
    # Fora do banco: escrever (antes) e ok | erro | cancelado (depois).
    # Negada: negado.
    acao: Mapped[str] = mapped_column(String(20))
    # Banco: os dados gravados. Vault: só o caminho da nota. Paperless: só ids inteiros. Nunca texto.
    dados: Mapped[dict] = mapped_column(JSON)
    autor: Mapped[str | None] = mapped_column(String(80))


class Chamada(Base):
    """Toda chamada de ferramenta, inclusive leitura (registro.py, Passo 8b3). Só INSERT.

    Nunca guarda argumento nem conteúdo: só de onde a chamada veio e como terminou.
    """

    __tablename__ = "chamadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Início da chamada.
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # Nome da ferramenta; `<nome invalido>` se o nome pedido não for só letras, números e `_`.
    ferramenta: Mapped[str] = mapped_column(String(60))
    # ok | erro | negado | cancelado
    resultado: Mapped[str] = mapped_column(String(20))
    # Conta conferida na lista (claim `identidade`); `anonimo` sem token.
    autor: Mapped[str | None] = mapped_column(String(80))
    # clientInfo do cliente MCP (nome e versão), como o cliente declarou.
    cliente: Mapped[str | None] = mapped_column(String(80))
    versao_cliente: Mapped[str | None] = mapped_column(String(40))
    # Cabeçalho mcp-session-id (vazio sem HTTP ou sem sessão).
    sessao: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    # Nome do modelo DECLARADO pelo próprio modelo (parâmetro `modelo` ou `_meta._modelo`). Não é conferido.
    modelo_declarado: Mapped[str | None] = mapped_column(String(60))
    duracao_ms: Mapped[int] = mapped_column(Integer)
    # Linha de `auditoria` da chamada: `escrever` (peças), `negado` sem `escrever`, ou `criar`/`desfazer` (banco).
    auditoria_id: Mapped[int | None]
