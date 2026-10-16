# Implantação: teste no MacBook → produção no i7

Sequência combinada: primeiro roda tudo no MacBook até ficar estável; só depois vai para a
máquina dedicada. Marque `[x]` conforme avança.

## Etapa A — Teste no MacBook

- [x] A1. Instalar Docker Desktop (ou OrbStack) e confirmar `docker compose version`
- [x] A2. `git clone https://github.com/Leonardo-Richeto/assistente-pessoal && cd assistente-pessoal`
- [x] A3. Rodar os testes: `cd servidor && uv sync && uv run pytest` (devem passar todos)
- [ ] A4. Instalar o Tailscale (se a versão da App Store não aceitar Funnel, usar a standalone);
      no painel, habilitar HTTPS e Funnel para o Mac
- [ ] A5. `tailscale funnel --bg 8000` → anotar a URL `https://<mac>.<tailnet>.ts.net`
- [ ] A6. Criar um GitHub OAuth App **de teste**
      - Homepage: URL do A5 · Callback: `<URL do A5>/auth/callback`
- [x] A7 (parcial, 2026-10-16: `.env` local de teste com `AUTH_DESATIVADA=true`, sem credenciais GitHub; refazer no Passo 5). `cp .env.example .env` e preencher:
      senhas e `JWT_SIGNING_KEY` (`openssl rand -base64 32`), `PUBLIC_BASE_URL` (A5),
      `AUTH_PROVEDOR=github`, credenciais do A6, `GITHUB_LOGINS_PERMITIDOS=Leonardo-Richeto`.
      Vault e Paperless vazios por enquanto.
- [x] A8 (2026-10-16, MacBook arm64). `docker compose up -d --build` e `docker compose logs -f servidor` (erro no build → guardar o log)
- [ ] A9. claude.ai → Configurações → Conectores → conector personalizado → `<URL do A5>/mcp` → login GitHub
- [ ] A10. Teste pelo iPhone: registrar gasto → consultar → desfazer; registrar ponto → consultar horas
- [ ] A11. (Opcional) Testar o vault com uma **cópia** do vault em `VAULT_PATH`
- [ ] A12. Usar alguns dias; anotar aqui o que faltou ou incomodou

Observações do teste:
-

## Etapa B — Produção no i7

Só começa com a Etapa A estável.

- [ ] B1. Inventário completo de **todas** as máquinas (specs, configuração, saúde SMART dos discos, VMs) → nota no vault + resumo em `docs/inventario.md` (roteiro em `CONTEXTO.md`)
- [ ] B2. Instalar Debian ou Ubuntu Server mínimo no i7, Docker e Git
- [ ] B3. Clonar o repo no i7
- [ ] B4. Tailscale no i7, HTTPS + Funnel habilitados, `tailscale funnel --bg 8000` → nova URL
- [ ] B5. Atualizar o GitHub OAuth App para a nova URL (ou criar um de produção) e desligar o Funnel do Mac
- [ ] B6. Novo `.env` no i7 (**senhas novas**, não reaproveitar as do teste)
- [ ] B7. `docker compose up -d --build`
- [ ] B8. No claude.ai: remover o conector de teste e adicionar o de produção (`<nova URL>/mcp`)
- [ ] B9. Repetir os testes do A10
- [ ] B10. Decidir se os registros feitos no teste vão para produção (`pg_dump` do Mac → restore no i7) ou se começa limpo
- [ ] B11. Seguir para a Fase 2 do `PLANO.md` (Paperless e vault de verdade)
