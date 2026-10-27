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
    # "pluggy:<id da transação>" ou "pluggy-parcela:<chave da compra>:<nn>" (Ficha 10, regras 6 e 10).
    id_externo: Mapped[str | None] = mapped_column(String(120), unique=True)
    # Falso = gasto do banco que o dono ainda não conferiu (Ficha 10, regra 8). O manual nasce conferido.
    conferido: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Gasto que este, vindo do banco, parece repetir: um manual ou outro do banco com outro id (Ficha 10, regra 14).
    # Só aviso; nada se desfaz sozinho.
    duplicata_de: Mapped[int | None] = mapped_column(Integer)
    # Parcela futura lançada pelo worker antes de o banco trazê-la (Ficha 10, regra 6). Vira falso quando chega.
    previsto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


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


class Sessao(Base):
    """Resumo de uma sessão do Claude Code, feito por regra no hook da máquina (ficha 5, regra 9; Passo 11).

    Só INSERT e SELECT (migração 0006): nada se apaga nem se altera. A sessão retomada chega de novo com outro
    `fim` e vira linha nova; a consulta pega a mais nova de cada `sessao`. O mesmo (`sessao`, `fim`) não entra
    duas vezes (índice único; `python -m assistente.sessoes importar` conta a repetida e segue).
    Os textos vêm de fora (transcript): são dado, nunca instrução. Datas gravadas em UTC.
    """

    __tablename__ = "sessoes"
    # O índice único começa por `sessao`: serve também de índice da busca por sessão.
    __table_args__ = (
        Index("ix_sessoes_sessao_fim", "sessao", "fim", unique=True),
        Index("ix_sessoes_fim", "fim"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Id da sessão do Claude Code (^[A-Za-z0-9-]{8,80}$, conferido na importação).
    sessao: Mapped[str] = mapped_column(String(80))
    projeto: Mapped[str] = mapped_column(String(120))
    raiz: Mapped[str] = mapped_column(String(300))
    maquina: Mapped[str] = mapped_column(String(60))
    inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duracao_min: Mapped[int] = mapped_column(Integer)
    # Primeira mensagem digitada pelo dono (o hook corta em 120).
    titulo: Mapped[str] = mapped_column(String(200))
    # Listas: caminhos (até 50), comandos sem conteúdo (até 30), commits {id, mensagem} (até 20).
    arquivos: Mapped[list] = mapped_column(JSON)
    comandos: Mapped[list] = mapped_column(JSON)
    commits: Mapped[list] = mapped_column(JSON)
    passagem: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # `reason` do SessionEnd do Claude Code (clear, logout, prompt_input_exit, other...).
    motivo_fim: Mapped[str] = mapped_column(String(40))
    # O hook leu só parte do transcript (sessão muito grande).
    parcial: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    versao_resumo: Mapped[int] = mapped_column(Integer)


class Sincronizacao(Base):
    """Uma rodada de um worker de ingestão (Ficha 10, regras 13 e 15). Só INSERT (migração 0007)."""

    __tablename__ = "sincronizacoes"
    __table_args__ = (Index("ix_sincronizacoes_worker_inicio", "worker", "inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nome do worker, ex.: "pluggy".
    worker: Mapped[str] = mapped_column(String(30))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean)
    # Gastos gravados nesta rodada (parcelas futuras contam).
    novos: Mapped[int] = mapped_column(Integer, default=0)
    # Motivo curto da falha, sem segredo nem dado do banco (ex.: "Pluggy respondeu 401 em /auth").
    erro: Mapped[str | None] = mapped_column(String(300))


class Auditoria(Base):
    """Toda escrita feita por ferramenta passa por aqui, e toda tentativa negada (registro.py)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Nome da ferramenta; `<nome invalido>` se o nome pedido não for só letras, números e `_`.
    ferramenta: Mapped[str] = mapped_column(String(60))
    # Banco: gastos | ponto | atividades | notas_desatualizadas | sessoes (uma linha por importação, Passo 11).
    # Peças: vault | paperless. Outro nome: ferramenta.
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
