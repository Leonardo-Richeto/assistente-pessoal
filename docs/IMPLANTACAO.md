# Implantação: teste no MacBook → produção no i7

Sequência combinada: primeiro roda tudo no MacBook até ficar estável; só depois vai para a
máquina dedicada. Marque `[x]` conforme avança.

## Etapa A — Teste no MacBook

- [x] A1. Instalar Docker Desktop (ou OrbStack) e confirmar `docker compose version`
- [x] A2. `git clone https://github.com/Leonardo-Richeto/assistente-pessoal && cd assistente-pessoal`
- [x] A3. Rodar os testes: `cd servidor && uv sync && uv run pytest` (devem passar todos)
- [x] A4 (2026-10-17, standalone). Instalar o Tailscale (se a versão da App Store não aceitar Funnel, usar a standalone);
      no painel, habilitar HTTPS e Funnel para o Mac
- [x] A5 (2026-10-17: `https://<maquina>.<tailnet>.ts.net`, Funnel 443 → 127.0.0.1:8000). `tailscale funnel --bg 8000` → anotar a URL `https://<mac>.<tailnet>.ts.net`
- [x] A6 (2026-10-17: projeto `assistente-pessoal`, cliente Web "assistente teste mac", consentimento externo em teste). Criar um cliente OAuth do Google **de teste** (Google Cloud Console → APIs e serviços → Tela de consentimento OAuth: externo, em teste, com o seu Gmail como usuário de teste → Credenciais → ID do cliente OAuth → Aplicativo da Web)
      - Homepage: URL do A5 · Callback: `<URL do A5>/auth/callback`
- [x] A7 (2026-10-17: `.env` com URL do Funnel, `AUTH_PROVEDOR=google`, credenciais do A6 e `AUTH_DESATIVADA=false`; servidor de pé com login). `cp .env.example .env` e preencher:
      senhas e `JWT_SIGNING_KEY` (`openssl rand -base64 32`), `PUBLIC_BASE_URL` (A5),
      `AUTH_PROVEDOR=google`, credenciais do A6, `GOOGLE_EMAILS_PERMITIDOS=<seu Gmail>`.
      Vault e Paperless vazios por enquanto.
- [x] A8 (2026-10-16, MacBook arm64). `docker compose up -d --build` e `docker compose logs -f servidor` (erro no build → guardar o log)
- [x] A9 (2026-10-17: conector "Assistente (teste Mac)" conectado; "liste as categorias de gasto" respondeu só "teste"). claude.ai → Configurações → Conectores → conector personalizado → `<URL do A5>/mcp` → login Google
- [x] A10 (2026-10-17). Teste pelo iPhone: registrar gasto → consultar → desfazer; registrar ponto → consultar horas
- [x] A11 (2026-10-17: servidor com a cópia em `~/assistente-teste/vault`; 24 ferramentas, busca, leitura e escrita ok no servidor; teste pelo app com o Leonardo pendente). (Opcional) Testar o vault com uma **cópia** do vault em `VAULT_PATH`
- [ ] A12. Usar alguns dias; anotar aqui o que faltou ou incomodou

Observações do teste:
-

## Etapa B — Produção no i7

Só começa com a Etapa A estável.

- [ ] B1. Inventário completo de **todas** as máquinas (specs, configuração, saúde SMART dos discos, VMs) → nota no vault + resumo em `docs/inventario.md` (roteiro em `CONTEXTO.md`)
- [ ] B2. Instalar Debian ou Ubuntu Server mínimo no i7, Docker e Git
- [ ] B3. Clonar o repo no i7
- [ ] B4. Tailscale no i7, HTTPS + Funnel habilitados, `tailscale funnel --bg 8000` → nova URL
- [ ] B5. Atualizar o cliente OAuth do Google para a nova URL (ou criar um de produção) e desligar o Funnel do Mac
- [ ] B6. Novo `.env` no i7 (**senhas novas**, não reaproveitar as do teste)
- [ ] B7. `docker compose up -d --build`
- [ ] B8. No claude.ai: remover o conector de teste e adicionar o de produção (`<nova URL>/mcp`)
- [ ] B9. Repetir os testes do A10
- [ ] B10. Decidir se os registros feitos no teste vão para produção (`pg_dump` do Mac → restore no i7) ou se começa limpo
- [ ] B11. Seguir para a Fase 2 do `PLANO.md` (Paperless e vault de verdade)
