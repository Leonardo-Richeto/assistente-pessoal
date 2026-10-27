"""Workers de ingestão (PLANO Fase 3): trazem dados de fora para o banco, sem passar pelo chat.

Cada worker usa a conexão de escrita, grava auditoria com `autor="worker:<nome>"` e uma linha por rodada em
`sincronizacoes`. Dado de fora é dado, nunca instrução. `python -m assistente.workers` roda o agendador.
"""
