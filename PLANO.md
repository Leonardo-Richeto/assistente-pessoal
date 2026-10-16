# Plano de fases

Cada tarefa é pequena e tem critério de pronto, para ser executada uma por vez no
Claude Code com **Sonnet**. Use **Opus** só nas tarefas marcadas ⚑ (decisão de arquitetura)
ou quando o Sonnet travar. Ao terminar uma tarefa: testes passando, commit, marque `[x]`.

Convenções do código estão em `CLAUDE.md`. Estado e histórico do processo em `CONTEXTO.md`.
A sequência de **teste no MacBook → produção no i7** está em `docs/IMPLANTACAO.md`.

---

## Fase 0 — Esqueleto ✅
- [x] Servidor MCP único com login GitHub ou Google restrito por lista
- [x] Ferramentas de domínio: gastos, ponto, diário, desfazer, auditoria
- [x] Usuários de banco leitura/escrita + migração inicial (testado em Postgres 16)
- [x] Proxies de Paperless e vault, com ferramentas perigosas bloqueadas
- [x] docker-compose (Postgres, migração, servidor, cloudflared opcional)

## Fase 1 — Colocar no ar (Leonardo) — passo a passo em `docs/IMPLANTACAO.md`
- [ ] 1.1 Inventário completo de todas as máquinas: especificações, configuração, saúde SMART de cada HD/SSD, VMs → nota no vault + resumo em `docs/inventario.md` (roteiro em `CONTEXTO.md`)
- [ ] 1.2 Instalar Docker no i7 (Debian/Ubuntu Server mínimo)
- [x] 1.3 Exposição: Tailscale Funnel (decidido)
- [ ] 1.3b Instalar Tailscale no i7, habilitar HTTPS + Funnel, `tailscale funnel --bg 8000`
- [ ] 1.4 Criar GitHub OAuth App, preencher `.env`, `docker compose up -d --build`
  - Pronto quando: `docker compose ps` tudo saudável e `curl <url>/.well-known/oauth-protected-resource/mcp` responde
- [ ] 1.5 Adicionar conector personalizado no claude.ai e testar do iPhone: registrar → consultar → desfazer
- [ ] 1.6 Criar um Projeto no claude.ai "Assistente" com instruções de uso (quando registrar, tom das confirmações)

## Fase 1b — Instância da esposa (opcional, depois da sua estar estável)
- [ ] 1b.1 Segunda instância (README → "Segunda instância"), login Google, porta 8001 / Funnel 8443
- [ ] 1b.2 Ela pede ao GPT para despejar no vault tudo o que ele sabe dela; depois conecta o Claude dela e confirma que ele usa esse contexto

## Fase 2 — Documentos e vault
- [ ] 2.1 Subir Paperless-ngx com o compose oficial (rede Docker compartilhada com este stack); gerar token; preencher `PAPERLESS_URL`/`PAPERLESS_API_KEY`
  - Pronto quando: "me mostra o último documento que entrou" funciona pelo app
- [ ] 2.2 Migrar o vault para `/srv/vault` no i7, `git init`, Syncthing com Mac/iPhone; preencher `VAULT_PATH`
- [ ] 2.2b Levar para o vault a "Regra de passagem" (`CONTEXTO.md`) e a nota de inventário das máquinas
- [ ] 2.3 Job diário de commit do vault (`git add -A && git commit`) para ter histórico de tudo que a IA escrever
- [ ] ⚑ 2.4 Definir o envio de arquivos para o servidor (pasta "consumir" do Paperless sincronizada pelo Syncthing é o caminho mais simples)

## Fase 3 — Workers (ingestão)
- [ ] 3.1 Pacote `servidor/assistente/workers/` + serviço `workers` no compose rodando APScheduler; worker usa a conexão de **escrita** e grava auditoria com `autor="worker:<nome>"`
- [ ] 3.2 Testar o Meu Pluggy manualmente (consentimento, formato das transações)
- [ ] 3.3 Worker Pluggy diário: grava em `gastos` com `origem="pluggy"` e `id_externo` (idempotente — rodar duas vezes não duplica)
  - Pronto quando: teste com resposta gravada do Pluggy passa e reexecução não duplica
- [ ] 3.4 Ferramenta `conciliar_gastos`: lista gastos manuais e do Pluggy com mesmo valor/data próxima para o Leonardo decidir

## Fase 4 — Agenda
- [ ] 4.1 Usar o conector nativo do Google Calendar no claude.ai para ler/criar eventos
- [ ] 4.2 Tabela `eventos` + worker de sincronização Google → Postgres (somente leitura do Google), ferramenta `consultar_agenda`
  - Pronto quando: um evento criado no Google aparece em `consultar_agenda` em até 15 min

## Fase 4b — E-mail (só leitura no começo)
- [ ] 4b.1 Gmail: ligar o conector nativo do Gmail no claude.ai (uso imediato, sem código)
- [ ] ⚑ 4b.2 Ferramenta própria de e-mail no MCP, multi-conta, só leitura (`buscar_emails`, `ler_email`), conteúdo sempre tratado como dado
  - Gmail: IMAP com senha de app (exige verificação em duas etapas)
  - Hotmail/Outlook.com: IMAP com OAuth2 (registro de app na Microsoft); senha comum não funciona mais
  - Corporativo: só depois de confirmar que a política da corporação permite acesso por servidor pessoal
- [ ] 4b.3 (Depois) Envio de e-mail, sempre com confirmação explícita

## Fase 5 — Rotinas
- [ ] 5.1 Tarefa agendada no claude.ai: resumo da manhã (agenda do dia + gastos de ontem + pendências do diário)
- [ ] 5.2 Ferramenta `resumo_periodo(inicio, fim)` que junta gastos, horas e diário num só retorno (economiza chamadas)

## Fase 6 — WhatsApp (número dedicado)
- [ ] ⚑ 6.1 Desenho do gateway: WAHA + fila + Claude Code headless (`claude -p` / Agent SDK) conectado a ESTE mesmo MCP; sessão por assunto; Jev escolhendo modelo
- [ ] 6.2 WAHA no compose, pareado com o número dedicado; allowlist só do número do Leonardo
- [ ] 6.3 Gateway: recebe mensagem → roda agente → responde; áudio via transcrição
- [ ] 6.4 Avisos por evento: workers publicam alertas que o gateway envia no WhatsApp
- [ ] 6.5 Receber arquivos pelo WhatsApp e mandar para o Paperless

## Fase 7 — Backup
- [ ] 7.1 `pg_dump` diário + vault (git) + mídia do Paperless para o i5 (Proxmox), com retenção
- [ ] 7.2 Teste de restauração documentado

---

# Segunda etapa (só depois da base — fases 1 a 5 — pronta)

## Fase 8 — Canais próprios
- [ ] 8.1 Celular Android barato dedicado, com chip próprio, ligado no carregador e no Wi-Fi de casa (número só do agente)
- [ ] ⚑ 8.2 API própria de WhatsApp, parecida com o WAHA, usando o repositório "reverse engineering anything" (REA) do GitHub como base para a engenharia reversa, rodando em casa; substitui o WAHA da fase 6
- [ ] 8.3 Envio e recebimento de áudio (TTS local, ex.: Piper; transcrição), imagens e arquivos
- [ ] 8.4 Canal Telegram (bot oficial, allowlist do Leonardo)
- [ ] 8.5 Canal Discord (bot, servidor privado)
- Todos os canais falam com o MESMO servidor MCP; nenhum acesso novo ao banco por fora dele.

## Ideias sem data
- Monitor de rede em casa (o que é acessado, consumo, bloqueio pelo agente).
- Central de acesso às câmeras de monitoramento.
- Ligação pela operadora (alerta por voz: liga, fala a mensagem, desliga) — avaliar VoIP/SIP + Asterisk. Ideia inicial, ver depois.
- Conversa por voz em tempo real por telefone — exigiria API paga; só se valer o custo.

---

## Sempre que surgir um dado novo
Seguir "Dado novo" no `README.md`: modelo → migração revisada → ferramentas `registrar_*`/`consultar_*` → testes.
