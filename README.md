# Assistente pessoal

Servidor MCP que roda em casa (máquina i7) e dá "mãos" ao Claude: o app do Claude
(iPhone/Mac/web) conecta nele como **conector personalizado** e passa a registrar gastos,
ponto e diário, ler o vault e buscar documentos no Paperless. Qualquer outro cliente MCP
(ex.: ChatGPT) conecta do mesmo jeito: o contexto fica aqui, não no modelo.

```
App do Claude ──► Tailscale Funnel ──► servidor MCP (login GitHub/Google, só quem está na lista)
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
| `servidor/assistente/auth.py` | Login via GitHub ou Google com lista de permitidos |
| `servidor/assistente/modelos.py` | Tabelas (SQLAlchemy) |
| `servidor/alembic/` | Migrações |
| `deploy/postgres/01-papeis.sh` | Cria os usuários de leitura e escrita |
| `PLANO.md` | Próximas fases, quebradas em tarefas |
| `docs/IMPLANTACAO.md` | Passo a passo: teste no MacBook → produção no i7 |

## Subir (referência)

Sequência completa com checklist em `docs/IMPLANTACAO.md`.

1. **Docker** instalado (`docker compose version` funcionando).
2. **Tailscale** no host, logado na sua tailnet. No painel do Tailscale, habilite HTTPS
   e Funnel para a máquina. Depois:
   ```bash
   tailscale funnel --bg 8000          # -> https://<maquina>.<tailnet>.ts.net
   ```
   Esse endereço é o `PUBLIC_BASE_URL`.
3. **Login** — crie as credenciais do provedor escolhido em `AUTH_PROVEDOR`.
   Callback (nos dois): `<PUBLIC_BASE_URL>/auth/callback`.
   - *GitHub:* Settings → Developer settings → OAuth Apps → New. Homepage = `PUBLIC_BASE_URL`.
     Preencha `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` e `GITHUB_LOGINS_PERMITIDOS`.
   - *Google:* console.cloud.google.com → novo projeto → "Tela de consentimento OAuth"
     (tipo Externo, adicione o e-mail como usuário de teste) → Credenciais → Criar ID do
     cliente OAuth → Aplicativo da Web → URI de redirecionamento = callback acima.
     Preencha `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GOOGLE_EMAILS_PERMITIDOS`.
4. `cp .env.example .env` e preencha (senhas e `JWT_SIGNING_KEY` com `openssl rand -base64 32`).
5. Subir:
   ```bash
   docker compose up -d --build
   docker compose logs -f servidor
   ```
6. **Conectar no Claude:** claude.ai → Configurações → Conectores → adicionar conector
   personalizado → URL `<PUBLIC_BASE_URL>/mcp`. Abre o login do provedor; entre com a conta
   permitida. Vale também no app do iPhone. Outro cliente MCP (ex.: ChatGPT em modo
   desenvolvedor) usa a mesma URL.
7. Teste: "registre um gasto de 10 reais de café" → "quanto gastei hoje?" → "desfaz".

### Segunda instância na mesma máquina (ex.: esposa)

Banco, vault e login separados — nada é compartilhado.
```bash
git clone <este repo> ~/assistente-esposa && cd ~/assistente-esposa
cp .env.example .env    # NOME_USUARIO, PORTA_HOST=8001, AUTH_PROVEDOR=google, VAULT_PATH próprio
tailscale funnel --bg --https=8443 8001          # PUBLIC_BASE_URL=https://<maquina>...ts.net:8443
docker compose -p assistente-esposa up -d --build
```

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
