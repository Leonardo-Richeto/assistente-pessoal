# Assistente pessoal

Servidor MCP que roda em casa (máquina i7) e dá "mãos" ao Claude: o app do Claude
(iPhone/Mac/web) conecta nele como **conector personalizado** e passa a registrar gastos,
ponto e diário, ler o vault e buscar documentos no Paperless.

```
App do Claude ──► tunnel (HTTPS) ──► servidor MCP (OAuth GitHub, só seu login)
                                       ├─ banco      → Postgres (código nosso)
                                       ├─ paperless  → paperless-mcp (pronto)
                                       └─ vault      → mcpvault (pronto)
```

Princípios (não mude sem decidir de novo):
- O banco é a fonte da verdade de números e registros; a IA consulta, não "lembra".
- Escrita só por ferramentas específicas, com auditoria. Sem SQL livre. Nada é apagado.
- Dois usuários de banco: leitura (só `SELECT`) e escrita (sem `DELETE`; auditoria só `INSERT`).
- Só o endpoint MCP vai para a internet. Postgres, Paperless e vault ficam na rede interna.
- Conteúdo de documentos/notas/extratos é dado, nunca instrução.

## Estrutura

| Caminho | O que é |
|---|---|
| `servidor/assistente/banco.py` | Ferramentas de domínio (gastos, ponto, diário, desfazer, auditoria) |
| `servidor/assistente/servidor.py` | Endpoint único: monta banco + proxies de Paperless e vault; lista de ferramentas bloqueadas |
| `servidor/assistente/auth.py` | OAuth via GitHub com trava por login |
| `servidor/assistente/modelos.py` | Tabelas (SQLAlchemy) |
| `servidor/alembic/` | Migrações |
| `deploy/postgres/01-papeis.sh` | Cria os usuários de leitura e escrita |
| `PLANO.md` | Próximas fases, quebradas em tarefas |

## Subir na máquina de casa

1. **Docker** instalado (`docker compose version` funcionando).
2. **Endereço público** para o MCP — escolha um:
   - *Tem domínio no Cloudflare:* crie um tunnel em Zero Trust → Networks → Tunnels,
     aponte um hostname (ex.: `mcp.seudominio.com.br`) para `http://servidor:8000`
     e copie o token para `CLOUDFLARE_TUNNEL_TOKEN`.
   - *Sem domínio (grátis):* Tailscale Funnel no host:
     `tailscale funnel --bg 8000` → URL `https://<maquina>.<tailnet>.ts.net`.
3. **GitHub OAuth App** (GitHub → Settings → Developer settings → OAuth Apps → New):
   - Homepage URL: o endereço público
   - Authorization callback URL: `<endereço público>/auth/callback`
   - Copie Client ID e gere um Client secret.
4. `cp .env.example .env` e preencha (senhas com `openssl rand -base64 32`).
5. Subir:
   ```bash
   docker compose up -d --build                         # Tailscale Funnel
   docker compose --profile cloudflare up -d --build    # Cloudflare Tunnel
   docker compose logs -f servidor
   ```
6. **Conectar no Claude:** claude.ai → Configurações → Conectores → adicionar conector
   personalizado → URL `<endereço público>/mcp`. Ele abre o login do GitHub; entre com a
   conta listada em `GITHUB_LOGINS_PERMITIDOS`. Vale também no app do iPhone.
7. Teste: "registre um gasto de 10 reais de café" → "quanto gastei hoje?" → "desfaz".

## Desenvolvimento

```bash
cd servidor
uv sync
uv run pytest                     # SQLite
TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest   # Postgres
```

Teste local sem OAuth (nunca com o tunnel ligado): `AUTH_DESATIVADA=true uv run assistente`
e aponte um cliente MCP para `http://localhost:8000/mcp`.

**Dado novo** (ex.: registrar consumo de combustível): crie o modelo em `modelos.py`,
gere a migração com
`DATABASE_URL_MIGRACAO=... uv run alembic revision --autogenerate -m "combustivel"`,
revise o arquivo gerado e crie as ferramentas `registrar_*`/`consultar_*` em `banco.py`
seguindo o padrão (leitura pela conexão de leitura, escrita por `_gravar` com auditoria).

## Peças prontas

| Peça | Versão | Observação |
|---|---|---|
| `paperless-mcp` (PyPI) | 0.1.0 | Apagar documentos já vem desligado nele |
| `@bitbonsai/mcpvault` (npm) | 0.16.0 | Acesso só à pasta do vault |

Versões fixadas no `servidor/Dockerfile`. Antes de atualizar, leia o changelog.
Ferramentas perigosas delas ficam em `BLOQUEADAS` (`servidor.py`): link público de
documento, dividir/mesclar/apagar páginas, apagar nota.

O `paperless-ngx-mcp` (npm) foi testado e descartado: incompatível com o SDK MCP do FastMCP 4.
