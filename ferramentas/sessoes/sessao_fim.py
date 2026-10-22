"""Hook SessionEnd do Claude Code: resume a sessão e grava na fila local.

Entrada (JSON na entrada padrão): session_id, transcript_path, cwd, reason.
Saída: sempre `{}` e código 0. Qualquer erro vai para `hooks.log` na pasta de
estado; o hook nunca trava nem interrompe a sessão (Ficha 5, regra 9).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def principal() -> None:
    try:
        import fila
    except Exception:  # noqa: BLE001
        return
    try:
        bruto = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        entrada = json.loads(bruto) if bruto.strip() else {}
        if not isinstance(entrada, dict):
            raise ValueError("entrada não é um objeto JSON")
        sessao = entrada.get("session_id")
        if not fila.id_valido(sessao):
            fila.log("sessao_fim: id de sessão ausente ou inválido; nada gravado")
            return
        import resumo

        dados = resumo.resumir(
            str(entrada.get("transcript_path") or ""),
            str(entrada.get("cwd") or os.getcwd()),
            sessao,
            str(entrada.get("reason") or ""),
        )
        fila.gravar(dados)
    except Exception as erro:  # noqa: BLE001 - falha em silêncio, só no log
        fila.log("sessao_fim: %s: %s" % (type(erro).__name__, erro))


if __name__ == "__main__":
    try:
        principal()
    finally:
        try:
            sys.stdout.write("{}\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)
