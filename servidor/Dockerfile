FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    PATH="/app/.venv/bin:$PATH"

# Node só para o MCP do vault (mcpvault é um pacote npm).
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# Peças prontas com versão fixada. Para atualizar: leia o changelog e mude aqui.
RUN npm install -g @bitbonsai/mcpvault@0.16.0 \
 && uv tool install paperless-mcp==0.1.0

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 assistente
USER assistente

EXPOSE 8000
CMD ["assistente"]
