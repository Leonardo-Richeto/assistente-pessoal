# Plano de fases

Cada tarefa é pequena e tem critério de pronto, para ser executada uma por vez no
Claude Code com **Sonnet**. Use **Opus** só nas tarefas marcadas ⚑ (decisão de arquitetura)
ou quando o Sonnet travar. Ao terminar uma tarefa: testes passando, commit, marque `[x]`.

Convenções do código estão em `AGENTS.md`. Estado e histórico do processo no vault (`10-projetos/assistente-pessoal/`, D22; ver `CONTEXTO.md`).
A sequência de **teste no MacBook → produção no i7** está em `docs/IMPLANTACAO.md`.

---

## Fase 0 — Esqueleto ✅
- [x] Servidor MCP único com login GitHub ou Google restrito por lista
- [x] Ferramentas de domínio: gastos, ponto, diário, desfazer, auditoria
- [x] Usuários de banco leitura/escrita + migração inicial (testado em Postgres 16)
- [x] Proxies de Paperless e vault, com ferramentas perigosas bloqueadas
- [x] docker-compose (Postgres, migração, servidor, cloudflared opcional)

## Fase 1 — Colocar no ar (Leonardo) — passo a passo em `docs/IMPLANTACAO.md`
**Máquina (Leonardo, 2026-10-18):** só o i7 fica ligado, com Debian 13 direto, sem Proxmox (o i7 está com Windows; 13 no lugar do 12, que saiu do suporte normal em 2026-06: 2026-10-23). Cada serviço roda no
seu próprio projeto Docker Compose; o que hoje está no i5 vem para o i7 (Fase 1c) e o i5 fica desligado. Motivo: conta de luz (as duas ligadas: estimativa
de R$ 29 a 47/mês). Sem backup do banco por enquanto; o vault tem Syncthing e GitHub (Fase 7). Revisto em 2026-10-19: backup diário
cifrado e migração pelo mesmo pacote (Fase 7, `docs/MIGRACAO.md`). Em 2026-10-21 (Leonardo): no início, sem backup ligado. **Em 2026-10-23 (Leonardo): backup ligado desde o início**, no HD de 500 GB do i7.
- [x] 1.9 `scripts/verificar.sh` testa o Funnel de dentro da tailnet: deu "ok" com o DNS público vazio (2026-10-23).
  Testar pela internet (DNS público + `curl --resolve` no IP do ingress) e falhar se o nome não existir.
  Feito no código em 2026-10-24 (`conferir_funnel_publico` no `lib.sh`, DoH no 1.1.1.1 e no 8.8.8.8;
  `scripts/testes/test_funnel_publico.sh`). No i7 em 2026-10-24: "Funnel pela internet ... sem token = 401", tudo ok.
- [x] 1.10 Conferir se o backup das 03:15 (para e religa o Tailscale) derruba o DNS público do Funnel (~20 min em
  2026-10-23 depois de um restart). Se derrubar: não parar o container do Tailscale no backup
  (2026-10-24: backup parou e religou às 03:18; o claude.ai chamou pelo Funnel às 06:34 sem falha. Uma falha curta logo
  depois das 03:18 não foi medida; de madrugada não pesa.)
- [ ] 1.8 (adiado) Desligar o i7 à noite: decidido em 2026-10-23 (Leonardo) rodar 24/7 e rever só se o consumo (1.7) pesar.
  Se voltar: Scheduled Power-On da BIOS para ligar, timer do systemd para desligar, e os timers das 03:15–03:40 antes do desligamento
- [x] 1.0 (2026-10-23) BIOS do i7 para economia (na instalação): C-states e package C-state no máximo, ASPM ligado, áudio e
  portas sem uso desligados, "AC power restore" ligado (volta sozinho depois de queda de luz). Lista completa: `docs/IMPLANTACAO.md` B2a
- [ ] 1.1 Inventário completo de todas as máquinas: especificações, configuração, saúde SMART de cada HD/SSD, VMs → nota no vault + resumo e roteiro em `docs/inventario.md`. i7 feito em 2026-10-24; falta o i5 (1c.1)
- [x] 1.2 (2026-10-23) Instalar Debian 13 direto no i7, com governador da CPU `powersave` e `powertop --auto-tune` no boot, e
  Docker (`docs/IMPLANTACAO.md` B2)
- [x] 1.3 Exposição: Tailscale Funnel (decidido)
- [x] 1.3b (2026-10-23; Funnel no container, nó `assistente`) Instalar Tailscale no i7, habilitar HTTPS + Funnel, `tailscale funnel --bg 8000`
- [x] 1.4 (2026-10-23; mesmo cliente do Mac, URL nova acrescentada) Criar o cliente OAuth do Google de produção (decisão de 2026-10-17; GitHub fica como alternativa), preencher `.env`, `docker compose up -d --build`
  - Pronto quando: `docker compose ps` tudo saudável e `curl <url>/.well-known/oauth-protected-resource/mcp` responde
- [ ] 1.5 Adicionar conector personalizado no claude.ai e testar do iPhone: registrar → consultar → desfazer
- [x] 1.6 Criar um Projeto no claude.ai "Assistente" com instruções de uso (quando registrar, tom das confirmações). Feito 2026-10-17 com o texto da ficha 1; no i7, só trocar o conector
- [ ] 1.7 Medir o consumo com a tomada medidora: i7 parado (24 h, só o Debian), depois com a stack (7 dias). Anotar
  W médio e R$/mês na nota `maquinas-do-assistente-pessoal` do vault. Pronto quando: os dois números estão lá

## Fase 1b — Instância da esposa (opcional, depois da sua estar estável)
- [ ] 1b.1 Segunda instância (README → "Segunda instância"), login Google, porta 8001 no host e nó Tailscale próprio
  (`TS_NOME=assistente-esposa`, URL própria na 443; a ideia antiga de Funnel na 8443 do mesmo nó ficou para trás com o
  Tailscale em container). Banco, vault, login e servidor separados: estimativa de ~300–400 MB de RAM por instância e quase nada de CPU (o i7 inteiro, com a stack, usava 1,0 GB de 15 GB em 2026-10-24).
  Decidido (Leonardo, 2026-10-24): **Paperless único**, com um usuário e um token por pessoa (cada token só vê os
  documentos do dono), se o Paperless permitir isso com segurança; senão, um por pessoa. Ver 2.1.
- [ ] 1b.2 Ela pede ao GPT para despejar no vault tudo o que ele sabe dela; depois conecta o Claude dela e confirma que ele usa esse contexto

## Fase 1c — Desligar o i5 (depois da Fase 1 estável)
- [ ] 1c.1 Inventário do i5 (B1): o que roda em cada VM, RAM e disco de cada serviço; conferir se cabe nos 16 GB do i7
- [ ] 1c.2 Subir no i7 cada serviço do i5 como projeto Docker Compose próprio, com rede e `.env` separados:
  agente-whatsapp (`-p agentewhatsapp`, dados por dump do banco dele) e os serviços de rede (AdGuard, WireGuard)
- [ ] 1c.3 Desligar o i5. O HD de 500 GB dele já foi para o i7 em 2026-10-23, como destino do backup (o HD avulso estava ruim); o i5 ficou só com o SSD
- [ ] 1c.4 Medir de novo (1.7) com tudo no i7

## Fase 2 — Documentos e vault
- [x] 2.1 Subir Paperless-ngx com o compose oficial (rede Docker compartilhada com este stack); gerar token; preencher `PAPERLESS_URL`/`PAPERLESS_API_KEY`
  - Decisão de 2026-10-24 (Leonardo): um Paperless só para o Leonardo e a esposa (1b), um usuário e um token por
    pessoa. Por isso ele fica fora do compose do assistente, como projeto próprio, com backup próprio. Isso
    substitui a ideia de "Paperless no mesmo compose" do prompt antigo do PC Windows e muda a 7.3: o
    `exportar.sh` do assistente não leva os documentos.
  - Pronto quando: "me mostra o último documento que entrou" funciona pelo app
  - 2026-10-24 (Opus 5.5, Mac): Ficha 6 aprovada; projeto `paperless/` (v3.3.4, digest fixo, só 127.0.0.1, rede
    por instância), usuários comuns, workflows de dono por pasta, conferência diária, backup e restauração ensaiados
    com documentos sintéticos (`tests/test_paperless_isolamento.py`, 17 testes). Word e Excel pelo Tika e
    Gotenberg (Leonardo, 2026-10-24: "preciso disso"); o original fica guardado.
  - 2026-10-24 (Opus 5.5, guiando do Mac): no i7, `docs/IMPLANTACAO.md` P1–P6. Timers de backup (03:45) e
    conferência (07:00), ensaio de restauração no Mac com o pacote do i7 e, pelo app, "me mostra o último documento
    que entrou" e a recusa de compartilhar. Rota padrão do servidor fixa na rede do assistente (`gw_priority`).
- [ ] 2.2 Migrar o vault para `/srv/assistente/vault` no i7, Syncthing com todos os aparelhos (Mac, iPhone, PC Windows) e GitHub privado mantido por enquanto (decisão de 2026-10-17); preencher `VAULT_PATH`. Detalhe: `SPRINT.md` B12
- [x] 2.2b (regra em 2026-10-16, `registro-temporario-de-sprint-na-raiz`; inventário em `maquinas-do-assistente-pessoal`) Levar para o vault a "Regra de passagem" e a nota de inventário das máquinas
- [ ] 2.3 Job diário de commit do vault (`git add -A && git commit`) para ter histórico de tudo que a IA escrever
- [ ] ⚑ 2.4 Definir o envio de arquivos para o servidor (pasta "consumir" do Paperless sincronizada pelo Syncthing é o caminho mais simples)
- [ ] 2.5 Compartilhar documento entre o Leonardo e a esposa (Leonardo, 2026-10-24: "para implementação futura").
  Hoje a Ficha 6 (decisão 3) proíbe. Antes do código, ficha nova: quem compartilha, só ver ou editar, confirmação e
  desfazer. Depois, ferramenta própria (a `paperless-mcp` não muda permissões) com o token do dono e linha em
  `Auditoria`, conferência diária aceitando só esse compartilhamento e testes de isolamento. Estimativa: uma sessão.

## Fase 2b — Vault inteligente (ideias do ai-memory, Leonardo, 2026-10-21)
Vieram do estudo do vault com o [ai-memory](https://github.com/akitaonrails/ai-memory) em 2026-10-21; o porquê
está em `60-planos/metas/memoria-automatica-e-busca-no-vault.md` do vault. **Fronteira** (D5 de `decisoes-do-vault`):
o vault guarda o curado; sessões, chamadas e capturas automáticas ficam no banco e nunca viram nota sozinhas.
O código que lê o vault mora neste repo, nunca no vault: o servidor não executa arquivo que a IA ou o Syncthing
podem escrever. Itens que mudam o que o Claude do app faz (2b.2, 2b.6, 2b.7, 2b.8, 2b.9) precisam de ficha
"proposta" antes do código. 2b.1 e 2b.10 podem começar no Mac, antes do i7.

**Prioridade 1: alto valor, baixo custo**
- [x] 2b.1 `buscar_vault(texto, tipo?, status?)`: busca full-text (SQLite FTS5 em memória ou Postgres) com peso no
  título, nome do arquivo, tags e resumo `>`, sem acento obrigatório; devolve caminho, título e resumo das 5 melhores.
  Complementa `vault_search_notes`, que só acha a palavra exata. Prova de 2026-10-21: 123 notas em 48 ms
  - Pronto quando: o conjunto do 2b.10 roda e o resultado está anotado aqui
  - Medida (2026-10-21, 25 perguntas no vault real, 2b.10): acerto entre 5 = 24/25, em 1º = 19/25, MRR = 0.847, ~3 ms por busca; pesos (10,8,5,4,1).
- [x] ⚑ 2b.2 (Passo 4, 2026-10-21: `escrever_nota` com versão; `vault_write_note` só append/prepend) Escrita com conferência de versão: escrever no vault exige o hash do conteúdo lido e recusa se a nota
  mudou desde a leitura (edição pelo Syncthing no meio); `vault_write_note` sem `mode` deixa de aparecer
- [x] 2b.3 Barreira de segredo: antes de gravar no vault ou no banco, padrões do gitleaks recusam token, chave e
  senha; a referência `{{segredo:NOME}}` passa. O valor fica no Vaultwarden, fora do vault, e o servidor nunca o
  resolve (resolvido, iria para o contexto do modelo). O `commit-diario.sh` roda o gitleaks antes do commit
  - Feito (2026-10-22, Passo 5): middleware `BarreiraSegredo` recusa escrita do banco e do vault com cara de segredo; restaurar_nota confere o conteúdo do git; commit por escrita pula e foto recusa arquivo com segredo; importador de sessões redige; `commit-diario.sh` roda gitleaks v8.30.1 (digest fixo) e não comita se achar. Vault real: 125 notas, 0 achados.
- [ ] ⚑ 2b.3a Vaultwarden no i7 (Leonardo, 2026-10-21), em Docker Compose próprio, guarda os valores do 2b.3.
  Proposta: acesso só pela Tailscale, sem Funnel. Os dados dele entram no backup cifrado da Fase 7 (`exportar.sh`)
  - Pronto quando: o backup da Fase 7 leva o volume do Vaultwarden para fora do SSD do i7 e a restauração foi testada, antes do primeiro segredo.
    Enquanto o 7.1 estiver desligado (2026-10-21), o 2b.3a espera
- [x] 2b.4 (Passo 6, 2026-10-22: `vault_git.py`, foto da edição do dono antes de trocar; mover continua bloqueado) Commit por escrita: depois de cada escrita da IA, commit só do arquivo escrito, autor `claude-app`; o
  commit diário (2.3) fica para as edições do Leonardo. Ferramentas `historico_nota(caminho)` e
  `restaurar_nota(caminho, versao)`; depois, rever o bloqueio de `vault_move_note` e `vault_move_file`
- [x] 2b.5 `notas_recentes(n)`, pelo campo `atualizado` (Passo 3, 2026-10-21)

**Prioridade 2: depende do i7 no ar**
- [x] 2b.6 (Passo 7, 2026-10-22) `contexto_inicial()`: resumo do perfil, `onde-parei.md`, nota do dia e pendências numa chamada só, com
  limite de caracteres (hoje são 4 a 6 chamadas no começo da conversa)
- [x] 2b.7 (Passo 3, 2026-10-21) `ler_nota(caminho, relacionadas=true)`: devolve também links e backlinks a um salto, só com o resumo
- [x] 2b.8 (Passo 8, 2026-10-21: migração 0005, `consultar_desatualizadas`, `vault-marcas.service`) `marcar_desatualizada(caminho, motivo)`: grava no banco; o lint diário (M3) lista as notas marcadas
- [x] ⚑ 2b.9 (Passos 10 e 11, 2026-10-22: `ferramentas/sessoes/`, migração 0006, `consultar_sessoes`; envio real espera o i7) Captura das sessões do Claude Code: hook `SessionEnd` resume o transcript por regra (título, arquivos,
  comandos, commits, duração), fila local por máquina com chave contra duplicata, envio pela Tailscale com token de
  máquina para uma tabela de sessões; hook `SessionStart` avisa quando a sessão anterior do projeto terminou sem
  passagem. Ficha: o que a tabela guarda e por quanto tempo
- [x] 2b.10 Teste da busca: 20 a 30 perguntas, cada uma com a nota esperada; mede quantas vezes ela vem entre as 5
  primeiras; roda a cada mudança no ranking
  (2026-10-21: `servidor/assistente/vault_busca_medida.py`; perguntas em `90-meta/perguntas-da-busca.md` do vault, fora do repo público)
- [x] 2b.11 O lint avisa quando aparece arquivo `*.sync-conflict-*` no vault (2026-10-21: `deploy/vault/lint-diario.sh`,
  teste `scripts/testes/test_lint_conflitos.sh`)

**Prioridade 3: só se a necessidade aparecer**
- 2b.12 Busca por significado (pgvector com modelo local multilíngue), quando a busca por palavra errar com frequência
- 2b.13 Reordenar resultados com o Jev como juiz (o ai-memory tem adaptador: `docs/jev-reranker-adapter.md`)
- 2b.14 Fila de propostas de mudança em nota de regra ou decisão, aprovadas pelo Leonardo; a mesma fila da Fase 6b

Fora, decidido no estudo: decaimento, compactação e deduplicação de nota; consolidação por LLM; handoff entre
agentes e multiusuário; relações tipadas; consulta por data (o git já responde).

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

## Fase 6b — Fábrica de ferramentas (ideia aprovada para planejar, Leonardo, 2026-10-17)
Quando o Leonardo pede algo e falta ferramenta, o Claude pede a ferramenta; um agente no i7 a constrói e o
Leonardo aprova antes de subir. **Nunca sobe sem o sim do Leonardo:** o servidor lê dado de fora (notas,
documentos), e criar e publicar código sozinho viraria execução arbitrária por injeção de prompt. Mantém as
regras "sem comando arbitrário" e "só fica visível o que está em `PERMITIDAS`". Depende do Claude Code headless
no i7 (B11 da Sprint 2 e 6.1). Antes de implementar: ficha "proposta" em `docs/regras-de-negocio.md`.
- [ ] ⚑ 6b.1 `pedir_ferramenta(descricao, motivo)`: grava o pedido numa fila no banco (tabela `pedidos_ferramenta`,
  migração), auditado; só texto, não executa nada. O Claude responde ao pedido do momento com o que já existe e
  avisa que pediu a ferramenta. Pode vir antes do resto (até no Mac): serve de lista de desejos implementada à mão
- [ ] 6b.2 `consultar_pedidos_ferramenta` (leitura) e status do pedido (`aberto`, `em_construcao`, `aguardando_ok`,
  `aprovado`, `recusado`, `no_ar`)
- [ ] ⚑ 6b.3 Construtor no i7: Claude Code headless pega o pedido e escreve ficha proposta, código e testes num
  branch próprio, num container sem o `.env` de produção e sem rede além do necessário
- [ ] ⚑ 6b.4 Revisor independente automático no branch (regras do `AGENTS.md`: sem SQL livre, escrita auditada,
  classificação leitura/escrita, `PERMITIDAS`) e testes passando; reprovado volta ao construtor ou vira `recusado`
- [ ] ⚑ 6b.5 Aprovação do Leonardo: resumo com a ficha, o diff e o parecer do revisor (pelo app; depois da Fase 6,
  pelo WhatsApp); só o sim dele libera
- [ ] ⚑ 6b.6 Deploy depois do sim: merge, nome em `PERMITIDAS` e na classificação, `docker compose up -d --build`,
  401 sem token conferido; o status do pedido vira `no_ar` e o Claude avisa

## Fase 7 — Backup e portabilidade
**Retomada (Leonardo, 2026-10-19, "Plano de Portabilidade do Servidor"):** backup e migração são o mesmo processo.
Substitui o adiamento de 2026-10-18. Procedimento em `docs/MIGRACAO.md`.
**Backup desde o início (Leonardo, 2026-10-23; substitui o "sem backup" de 2026-10-21):** o i7 sobe com o 7.1 ligado, destino no HD de 500 GB (`/srv/backup-hd`). O HD tem o atributo SMART 184 (End-to-End) em FAILING_NOW: backup provisório. Disco novo só quando der; se o HD falhar antes, segue sem backup (Leonardo, 2026-10-23).
- [x] 7.0 Portabilidade (2026-10-19): estado em `ASSISTENTE_HOME` (bind mounts), imagens com digest, Tailscale em
  container com nome fixo, `scripts/{preparar_host,exportar,importar,verificar}.sh`, pacote `.tar.age` com manifesto
  e SHA-256. Ensaio com dados sintéticos passou no Windows (`scripts/testes/ensaio_migracao.sh`)
- [x] 7.1 Backup diário: `assistente-backup.timer` (03:15), 7 diários e 4 semanais. Falta no i7: ligar com
  `AGE_DESTINATARIO` e apontar `BACKUP_DESTINO` para o HD de 500 GB do i7 (`/srv/backup-hd`, `docs/IMPLANTACAO.md` B2d)
- [ ] 7.2 Ensaio de restauração mensal numa máquina ou VM descartável (o i5 vai ser desligado: rever onde). Primeiro
  ensaio em 2026-10-24 no Mac com `scripts/ensaiar_restauracao.sh` (pacote das 03:18): ok, 8 tabelas e 128 notas.
- [x] 7.3 (2026-10-24, Mac) Paperless com backup próprio, fora do pacote do assistente: `paperless/scripts/exportar.sh`
  (`document_exporter`, age), `importar.sh` e `ensaiar_restauracao.sh` (ensaio ok no Mac). No i7: timer do P4
- [ ] 7.4 Migração Mac → i7 com `verificar.sh` sem erro e teste com o i7 em outra rede (4G do celular)

---

# Segunda etapa (só depois da base — fases 1 a 5 — pronta)

## Fase 7b — Monitoramento de casa (só na máquina de produção, rede de casa) — planejado em 2026-10-17
Só faz sentido com o servidor ligado 24 h na rede de casa; no MacBook não roda.
**Sem terminal (Leonardo, 2026-10-17):** o modelo nunca ganha shell no i7 nem no roteador. Cada serviço
(AdGuard, WireGuard) ganha um agente pequeno com **ações fixas**, por API interna com token próprio; o
servidor MCP chama só essas ações. Escrita com confirmação, auditoria e desfazer. Pedido que nenhuma ação cobre vai
para a Fase 6b (fábrica de ferramentas).
- [ ] ⚑ 7b.1 Saúde do armazenamento: script no host (fora do container, porque `smartctl` precisa do disco) roda `smartctl -j` e `df` a cada hora e grava num diretório que um worker importa; tabela de leituras + ferramenta `consultar_saude_armazenamento` (SMART, uso do disco, tamanho do Postgres, idade do último backup); alerta quando setor realocado/pendente sobe, desgaste do SSD passa do limite ou o disco passa de 85%
- [ ] ⚑ 7b.2 Rede: DNS local (AdGuard Home, grátis) em container no i7 (1c.2), com o roteador apontando para ele; worker importa consultas por aparelho e consumo; ferramentas `consultar_rede` e `bloquear_dominio` (escrita, com confirmação). Cobre o "bloqueio de distrações" da nota `infraestrutura-de-casa` do vault
- [ ] 7b.4 WireGuard: `estado_wireguard` (leitura: peers, último handshake, bytes por peer) por um agente no host
  do WireGuard; ligar ou desligar peer (`alternar_peer_wireguard`, escrita com confirmação) fica para depois
- [ ] ⚑ 7b.5 Tráfego por aparelho: `consultar_trafego(aparelho, periodo)` (leitura). Fonte a escolher: coletor
  na rede (ntopng ou NetFlow/sFlow do roteador, se ele exportar) ou o que o AdGuard já dá; só metadado (bytes,
  destino, horário), nunca conteúdo
- [ ] 7b.3 Resumo semanal de saúde da casa (discos, backup, rede) na rotina da Fase 5

## Fase 8 — Canais próprios
- [ ] 8.1 Celular Android barato dedicado, com chip próprio, ligado no carregador e no Wi-Fi de casa (número só do agente)
- [ ] ⚑ 8.2 API própria de WhatsApp, parecida com o WAHA, usando o repositório "reverse engineering anything" (REA) do GitHub como base para a engenharia reversa, rodando em casa; substitui o WAHA da fase 6
- [ ] 8.3 Envio e recebimento de áudio (TTS local, ex.: Piper; transcrição), imagens e arquivos
- [ ] 8.4 Canal Telegram (bot oficial, allowlist do Leonardo)
- [ ] 8.5 Canal Discord (bot, servidor privado)
- Todos os canais falam com o MESMO servidor MCP; nenhum acesso novo ao banco por fora dele.

## Melhorias anotadas (Leonardo, 2026-10-18)
Vieram da análise do vault de 2026-10-18. O lado do vault já está feito (D4 de `decisoes-do-vault`): campo
`registro`, máquina `claude-app`, tipo `estado`, perfil e `90-meta/lint-do-vault.py`.
- [x] M1 (Ficha 3 aprovada e aplicada em 2026-10-18; falta colar o texto no Projeto) Ficha nova "proposta" em `docs/regras-de-negocio.md` (muda a ficha 1): a parte subjetiva vai para a nota do
  dia `50-diario/AAAA/AAAA-MM-DD.md` (acrescenta no fim), entrada `### HH:MM · claude-app — título` com a linha
  `registro: <tipo>-<id>`; `nota_vault` aponta para a nota do dia. Hoje vai para `00-inbox`, que o vault esvazia
  toda semana e que viraria dezenas de notas por mês para classificar
- [x] M2 (Ficha 3, aplicada em 2026-10-18) Na ficha 1, "como ler o vault": `MAPA.md` → índice `_*.md` da pasta → só as 12 primeiras linhas da nota
  (`vault_read_note_lines`, frontmatter e resumo) → nota inteira só se for a certa. Para pergunta pessoal, ler
  antes `20-areas/perfil-do-leonardo.md`
- [x] M3 (2026-10-18: `deploy/vault/lint-diario.sh` + timer, roteiro em `docs/SYNCTHING.md` §5; instalar no i7 junto com o B11) Lint do vault no i7: timer diário rodando `python3 -I /srv/vault/90-meta/lint-do-vault.py`, saída num
  arquivo que o resumo semanal (7b.3) lê; depois, se valer, ferramenta de leitura `saude_do_vault`
- [x] M5 (Ficha 4 aprovada e aplicada em 2026-10-18) Resumo da conversa no diário **quando o Leonardo pede**, com
  detalhe e contexto, sem código (D18 do vault). Registro automático por tarefa e resumo agendado descartados
- [x] M4 (2026-10-18: `SPRINT_HISTORICO.md`; `SPRINT_NOTAS.md` de ~29 mil para ~4,4 mil tokens) Arquivos de sprint mais baratos de ler: "Passos feitos" do `SPRINT_NOTAS.md` (~1.090 linhas, ~24 mil
  tokens por sessão) vão para um `SPRINT_HISTORICO.md` que a sessão não lê no início; estado do projeto num lugar só
  (`SPRINT_NOTAS` durante a sprint, `CONTEXTO` fora dela); a nota `_assistente-pessoal` do vault fica com objetivo e
  porquê, sem "Estado em". Revisto em 2026-10-24 (D22): fora da sprint, o estado mora no vault, no "Estado em" do
  `_assistente-pessoal`; o `CONTEXTO.md` virou um aviso. Muda a regra `registro-temporario-de-sprint-na-raiz` do vault

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
