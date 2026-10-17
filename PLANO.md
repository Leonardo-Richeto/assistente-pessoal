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
- [ ] 1.4 Criar o cliente OAuth do Google de produção (decisão de 2026-10-17; GitHub fica como alternativa), preencher `.env`, `docker compose up -d --build`
  - Pronto quando: `docker compose ps` tudo saudável e `curl <url>/.well-known/oauth-protected-resource/mcp` responde
- [ ] 1.5 Adicionar conector personalizado no claude.ai e testar do iPhone: registrar → consultar → desfazer
- [x] 1.6 Criar um Projeto no claude.ai "Assistente" com instruções de uso (quando registrar, tom das confirmações). Feito 2026-10-17 com o texto da ficha 1; no i7, só trocar o conector

## Fase 1b — Instância da esposa (opcional, depois da sua estar estável)
- [ ] 1b.1 Segunda instância (README → "Segunda instância"), login Google, porta 8001 / Funnel 8443
- [ ] 1b.2 Ela pede ao GPT para despejar no vault tudo o que ele sabe dela; depois conecta o Claude dela e confirma que ele usa esse contexto

## Fase 2 — Documentos e vault
- [ ] 2.1 Subir Paperless-ngx com o compose oficial (rede Docker compartilhada com este stack); gerar token; preencher `PAPERLESS_URL`/`PAPERLESS_API_KEY`
  - Pronto quando: "me mostra o último documento que entrou" funciona pelo app
- [ ] 2.2 Migrar o vault para `/srv/vault` no i7, Syncthing com todos os aparelhos (Mac, iPhone, PC Windows) e GitHub privado mantido por enquanto (decisão de 2026-10-17); preencher `VAULT_PATH`. Detalhe: `SPRINT.md` B12
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

## Fase 5b — Saúde (Apple Watch / app Saúde) — ideia aprovada para planejar, 2026-10-17
- [ ] 5b.1 Importar o histórico pelo `export.zip` do app Saúde (sem endpoint novo): tabelas de amostras, treinos e sono + migração; importação idempotente. **Guardar todas as amostras** (decisão do Leonardo, 2026-10-17), não só resumos
- [ ] ⚑ 5b.2 Endpoint só de ingestão (token próprio, só escrita, limite de chamadas) para a automação diária do app Atalhos do iOS
- [ ] 5b.3 Ferramentas `consultar_saude` / `resumo_saude(periodo)`; comentários sobre treino ou sono vão para o vault ligados por id
- Fora: app pago de exportação (premissa de não pagar nada além do Pro). Dado de saúde nunca vai para o vault nem para o GitHub.

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

## Fase 7b — Monitoramento de casa (só no i7, rede de casa) — planejado em 2026-10-17
Só faz sentido com o servidor ligado 24 h na rede de casa; no MacBook não roda.
- [ ] ⚑ 7b.1 Saúde do armazenamento: script no host (fora do container, porque `smartctl` precisa do disco) roda `smartctl -j` e `df` a cada hora e grava num diretório que um worker importa; tabela de leituras + ferramenta `consultar_saude_armazenamento` (SMART, uso do disco, tamanho do Postgres, idade do último backup); alerta quando setor realocado/pendente sobe, desgaste do SSD passa do limite ou o disco passa de 85%
- [ ] ⚑ 7b.2 Rede: DNS local (AdGuard Home, grátis) na VM de serviços de rede do i5 ou no i7, com o roteador apontando para ele; worker importa consultas por aparelho e consumo; ferramentas `consultar_rede` e `bloquear_dominio` (escrita, com confirmação). Cobre o "bloqueio de distrações" da nota `infraestrutura-de-casa` do vault
- [ ] 7b.3 Resumo semanal de saúde da casa (discos, backup, rede) na rotina da Fase 5

## Fase 8 — Canais próprios
- [ ] 8.1 Celular Android barato dedicado, com chip próprio, ligado no carregador e no Wi-Fi de casa (número só do agente)
- [ ] ⚑ 8.2 API própria de WhatsApp, parecida com o WAHA, usando o repositório "reverse engineering anything" (REA) do GitHub como base para a engenharia reversa, rodando em casa; substitui o WAHA da fase 6
- [ ] 8.3 Envio e recebimento de áudio (TTS local, ex.: Piper; transcrição), imagens e arquivos
- [ ] 8.4 Canal Telegram (bot oficial, allowlist do Leonardo)
- [ ] 8.5 Canal Discord (bot, servidor privado)
- Todos os canais falam com o MESMO servidor MCP; nenhum acesso novo ao banco por fora dele.

## Ideias sem data
- ~~Monitor de rede em casa~~ → virou a Fase 7b.2 (2026-10-17).
- Central de acesso às câmeras de monitoramento.
- Ligação pela operadora (alerta por voz: liga, fala a mensagem, desliga) — avaliar VoIP/SIP + Asterisk. Ideia inicial, ver depois.
- Conversa por voz em tempo real por telefone — exigiria API paga; só se valer o custo.

---

## Dados novos previstos (respostas do Leonardo, 2026-10-17)
Tudo vai para o banco (dado real e medível); comentário subjetivo vai para o vault, ligado por id (ficha 1).
Ordem sugerida de implementação, uma sprint por bloco:

| # | Bloco | Registros | Observação |
|---|---|---|---|
| 1 | Finanças | receitas e transferências; contas fixas e assinaturas (valor, dia, consumo de luz e água por mês); investimentos e dívidas/parcelamentos (posição por mês) | **sem aviso de vencimento** de conta; Pluggy (Fase 3) pode alimentar parte |
| 2 | Leitura e estudo | livros (título, páginas lidas por dia, início, fim); estudo diário (tema, duração) | o resumo do que aprendeu vai para o vault, ligado por id |
| 3 | Veículos | carro e patinete elétrico: abastecimento/recarga, km, manutenção, IPVA e seguro do carro | uma tabela de veículos, um registro por evento |
| 4 | Família e pets | eventos de saúde por pessoa ou pet (vacina, consulta, veterinário, crescimento) | filha (decisão de 2026-10-17): começar com vacinas, consultas, peso e altura; dado de criança fica só no banco de casa, nunca no vault/GitHub |
| 5 | Hábitos | marcação diária (ex.: água, leitura, tempo de tela) | definição dos hábitos com o Leonardo |
| 6 | Garantias e documentos | itens com prazo de garantia (ligados à nota fiscal no Paperless); documentos com vencimento (CNH etc.) | aviso de documento: confirmar |
| 7 | Saúde pessoal | peso e medidas (baixa prioridade); humor/energia/sono 1–5; Apple Watch na Fase 5b | — |
| 8 | Viagens | datas, destino, gastos ligados | não é frequente, mas entra |
| 9 | Metas | teto mensal por categoria e outras | o motivo fica no vault |

Fora: medicamentos e consultas frequentes (o Leonardo não tem).

**Bateria de perguntas ao subir no i7 (pedido do Leonardo, 2026-10-17):** quando cada bloco acima
estiver implementado em produção, o modelo faz ao Leonardo uma bateria de perguntas para popular os
dados iniciais (contas fixas, veículos, livros em andamento, pets, documentos e vencimentos,
hábitos etc.). Perguntas que ficaram para esse momento: aviso para documentos com vencimento
(recomendação: 60 dias antes); registrar o salário como receita (recomendação: sim); quais
hábitos marcar (3 a 5).

## Sempre que surgir um dado novo
Seguir "Dado novo" no `README.md`: modelo → migração revisada → ferramentas `registrar_*`/`consultar_*` → testes.
