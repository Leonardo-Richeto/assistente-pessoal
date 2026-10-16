"""Ferramentas de domínio sobre o banco.

Regras:
- Consultas usam a conexão de leitura (usuário só com SELECT).
- Escritas só acontecem por estas ferramentas, sempre com linha de auditoria.
- Nada é apagado: `desfazer_registro` marca o registro como desfeito.
- Não existe SQL livre.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import select

from .db import Bancos
from .modelos import Atividade, Auditoria, Gasto, Ponto

LEITURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

TipoPonto = Literal["entrada", "saida", "pausa_inicio", "pausa_fim"]
TipoRegistro = Literal["gasto", "ponto", "atividade"]
_MODELOS = {"gasto": Gasto, "ponto": Ponto, "atividade": Atividade}


def _autor() -> str | None:
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        return token.claims.get("login") if token else None
    except Exception:
        return None


def _brl(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _intervalo(inicio: date, fim: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    if fim < inicio:
        raise ToolError("A data final é anterior à inicial.")
    return (
        datetime.combine(inicio, time.min, tz),
        datetime.combine(fim + timedelta(days=1), time.min, tz),
    )


def horas_por_dia(registros: list[Ponto], tz: ZoneInfo) -> dict[str, float]:
    """Soma entrada→saída de cada dia e desconta as pausas. Pares incompletos são ignorados."""
    por_dia: dict[date, list[Ponto]] = defaultdict(list)
    for r in registros:
        por_dia[r.momento.astimezone(tz).date()].append(r)

    resultado = {}
    for dia, regs in sorted(por_dia.items()):
        regs.sort(key=lambda r: r.momento)
        total = timedelta()
        abertos: dict[str, datetime] = {}
        for r in regs:
            if r.tipo in ("entrada", "pausa_inicio"):
                abertos[r.tipo] = r.momento
            elif r.tipo == "saida" and "entrada" in abertos:
                total += r.momento - abertos.pop("entrada")
            elif r.tipo == "pausa_fim" and "pausa_inicio" in abertos:
                total -= r.momento - abertos.pop("pausa_inicio")
        resultado[dia.isoformat()] = round(total.total_seconds() / 3600, 2)
    return resultado


def criar_servidor_banco(bancos: Bancos, tz: ZoneInfo) -> FastMCP:
    mcp = FastMCP(
        "banco",
        instructions=(
            "Banco pessoal do Leonardo: gastos, ponto e diário. É a fonte da verdade para números "
            "e registros — consulte aqui em vez de confiar na memória. Depois de registrar, "
            "devolva a confirmação curta e ofereça desfazer."
        ),
    )

    def _agora() -> datetime:
        return datetime.now(tz)

    def _gravar(registro, ferramenta: str, tabela: str, dados: dict) -> int:
        with bancos.escrita.begin() as s:
            s.add(registro)
            s.flush()
            s.add(
                Auditoria(
                    ferramenta=ferramenta,
                    tabela=tabela,
                    registro_id=registro.id,
                    acao="criar",
                    dados=dados,
                    autor=_autor(),
                )
            )
            return registro.id

    # ---------------- Gastos ----------------

    @mcp.tool(annotations=ESCRITA)
    def registrar_gasto(
        valor: Annotated[Decimal, Field(gt=0, description="Valor em reais, ex.: 42.90")],
        descricao: str,
        categoria: Annotated[str, Field(description="Ex.: mercado, combustível, lazer. Reaproveite categorias já usadas.")],
        data: Annotated[date | None, Field(description="Padrão: hoje")] = None,
        forma_pagamento: str | None = None,
    ) -> dict:
        """Registra um gasto feito pelo Leonardo."""
        data = data or _agora().date()
        categoria = categoria.strip().lower()
        valor = valor.quantize(Decimal("0.01"))
        gid = _gravar(
            Gasto(data=data, valor=valor, descricao=descricao.strip(), categoria=categoria, forma_pagamento=forma_pagamento),
            "registrar_gasto",
            "gastos",
            {"data": data.isoformat(), "valor": str(valor), "descricao": descricao, "categoria": categoria,
             "forma_pagamento": forma_pagamento},
        )
        return {
            "id": gid,
            "confirmacao": f"Registrado: {_brl(valor)} — {descricao} ({categoria}) em {data:%d/%m}. Desfazer?",
        }

    @mcp.tool(annotations=LEITURA)
    def consultar_gastos(inicio: date, fim: date, categoria: str | None = None) -> dict:
        """Lista gastos no período (datas inclusivas), com total e soma por categoria."""
        if fim < inicio:
            raise ToolError("A data final é anterior à inicial.")
        q = select(Gasto).where(Gasto.data >= inicio, Gasto.data <= fim, Gasto.desfeito.is_(False))
        if categoria:
            q = q.where(Gasto.categoria == categoria.strip().lower())
        with bancos.leitura() as s:
            gastos = s.scalars(q.order_by(Gasto.data, Gasto.id)).all()
        por_categoria: dict[str, Decimal] = defaultdict(Decimal)
        for g in gastos:
            por_categoria[g.categoria] += g.valor
        return {
            "total": str(sum((g.valor for g in gastos), Decimal("0"))),
            "por_categoria": {k: str(v) for k, v in sorted(por_categoria.items(), key=lambda kv: -kv[1])},
            "gastos": [
                {"id": g.id, "data": g.data.isoformat(), "valor": str(g.valor), "descricao": g.descricao,
                 "categoria": g.categoria, "forma_pagamento": g.forma_pagamento, "origem": g.origem}
                for g in gastos
            ],
        }

    @mcp.tool(annotations=LEITURA)
    def listar_categorias_gasto() -> list[str]:
        """Categorias já usadas, para manter a nomenclatura consistente."""
        with bancos.leitura() as s:
            return list(s.scalars(select(Gasto.categoria).distinct().order_by(Gasto.categoria)))

    # ---------------- Ponto ----------------

    @mcp.tool(annotations=ESCRITA)
    def registrar_ponto(
        tipo: TipoPonto,
        momento: Annotated[datetime | None, Field(description="Padrão: agora. Sem fuso = horário de Brasília.")] = None,
        observacao: str | None = None,
    ) -> dict:
        """Registra entrada, saída ou pausa do trabalho."""
        momento = momento or _agora()
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=tz)
        pid = _gravar(
            Ponto(momento=momento, tipo=tipo, observacao=observacao),
            "registrar_ponto",
            "ponto",
            {"momento": momento.isoformat(), "tipo": tipo, "observacao": observacao},
        )
        local = momento.astimezone(tz)
        return {"id": pid, "confirmacao": f"Registrado: {tipo.replace('_', ' ')} às {local:%H:%M} de {local:%d/%m}. Desfazer?"}

    @mcp.tool(annotations=LEITURA)
    def consultar_ponto(inicio: date, fim: date) -> dict:
        """Registros de ponto no período e horas trabalhadas por dia (descontando pausas)."""
        de, ate = _intervalo(inicio, fim, tz)
        with bancos.leitura() as s:
            regs = s.scalars(
                select(Ponto).where(Ponto.momento >= de, Ponto.momento < ate, Ponto.desfeito.is_(False)).order_by(Ponto.momento)
            ).all()
        horas = horas_por_dia(list(regs), tz)
        return {
            "horas_por_dia": horas,
            "total_horas": round(sum(horas.values()), 2),
            "registros": [
                {"id": r.id, "momento": r.momento.astimezone(tz).isoformat(), "tipo": r.tipo, "observacao": r.observacao}
                for r in regs
            ],
        }

    # ---------------- Diário ----------------

    @mcp.tool(annotations=ESCRITA)
    def registrar_atividade(
        descricao: str,
        tags: Annotated[list[str] | None, Field(description="Ex.: ['trabalho', 'estudo']")] = None,
        momento: Annotated[datetime | None, Field(description="Padrão: agora")] = None,
    ) -> dict:
        """Registra no diário algo que o Leonardo fez."""
        momento = momento or _agora()
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=tz)
        tags_txt = ",".join(t.strip().lower() for t in tags) if tags else None
        aid = _gravar(
            Atividade(momento=momento, descricao=descricao.strip(), tags=tags_txt),
            "registrar_atividade",
            "atividades",
            {"momento": momento.isoformat(), "descricao": descricao, "tags": tags_txt},
        )
        return {"id": aid, "confirmacao": f"Anotado no diário de {momento.astimezone(tz):%d/%m}. Desfazer?"}

    @mcp.tool(annotations=LEITURA)
    def consultar_atividades(inicio: date, fim: date, busca: str | None = None) -> list[dict]:
        """Diário do período. `busca` filtra por texto na descrição ou nas tags."""
        de, ate = _intervalo(inicio, fim, tz)
        q = select(Atividade).where(Atividade.momento >= de, Atividade.momento < ate, Atividade.desfeito.is_(False))
        if busca:
            termo = f"%{busca.lower()}%"
            q = q.where(Atividade.descricao.ilike(termo) | Atividade.tags.ilike(termo))
        with bancos.leitura() as s:
            regs = s.scalars(q.order_by(Atividade.momento)).all()
        return [
            {"id": a.id, "momento": a.momento.astimezone(tz).isoformat(), "descricao": a.descricao,
             "tags": a.tags.split(",") if a.tags else []}
            for a in regs
        ]

    # ---------------- Desfazer e auditoria ----------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    def desfazer_registro(tipo: TipoRegistro, id: int) -> str:
        """Desfaz um registro (gasto, ponto ou atividade). O dado fica no banco marcado como desfeito."""
        modelo = _MODELOS[tipo]
        with bancos.escrita.begin() as s:
            reg = s.get(modelo, id)
            if reg is None:
                raise ToolError(f"Não achei {tipo} com id {id}.")
            if reg.desfeito:
                return f"O {tipo} {id} já estava desfeito."
            reg.desfeito = True
            s.add(Auditoria(ferramenta="desfazer_registro", tabela=modelo.__tablename__, registro_id=id,
                            acao="desfazer", dados={}, autor=_autor()))
        return f"Desfeito: {tipo} {id}."

    @mcp.tool(annotations=LEITURA)
    def consultar_auditoria(limite: Annotated[int, Field(ge=1, le=200)] = 20) -> list[dict]:
        """Últimas escritas feitas pelas ferramentas."""
        with bancos.leitura() as s:
            regs = s.scalars(select(Auditoria).order_by(Auditoria.id.desc()).limit(limite)).all()
        return [
            {"momento": a.momento.astimezone(tz).isoformat() if a.momento else None, "ferramenta": a.ferramenta,
             "tabela": a.tabela, "registro_id": a.registro_id, "acao": a.acao, "dados": a.dados, "autor": a.autor}
            for a in regs
        ]

    return mcp
