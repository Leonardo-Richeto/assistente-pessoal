#!/bin/bash
# Roda uma única vez, na criação do volume do Postgres.
# Cria os usuários da aplicação com o mínimo de permissão:
#   assistente_leitura -> só SELECT
#   assistente_escrita -> SELECT, INSERT, UPDATE (sem DELETE); auditoria só INSERT
# O dono do banco ($POSTGRES_USER) é usado apenas pelas migrações (Alembic).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v senha_leitura="$SENHA_LEITURA" -v senha_escrita="$SENHA_ESCRITA" <<'SQL'
CREATE ROLE assistente_leitura LOGIN PASSWORD :'senha_leitura';
CREATE ROLE assistente_escrita LOGIN PASSWORD :'senha_escrita';

GRANT CONNECT ON DATABASE :"DBNAME" TO assistente_leitura, assistente_escrita;
GRANT USAGE ON SCHEMA public TO assistente_leitura, assistente_escrita;

-- Valem para toda tabela que as migrações criarem no futuro.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO assistente_leitura;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO assistente_escrita;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO assistente_escrita;
SQL
