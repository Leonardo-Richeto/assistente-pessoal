# Contexto do projeto (diário de passagem entre modelos)

Este arquivo é a memória do processo. Quem trabalhar no projeto (qualquer modelo, em qualquer
sessão) **lê este arquivo primeiro** e, ao terminar, **atualiza** as seções abaixo e escreve o
prompt para a próxima etapa. Ver "Regra de passagem" no fim.

Leitura complementar: `README.md` (arquitetura e princípios), `PLANO.md` (fases e tarefas),
`docs/IMPLANTACAO.md` (teste no MacBook → produção no i7), `CLAUDE.md` (regras de código).

---

## Estado atual

- **Durante uma sprint, o estado vivo fica só em `SPRINT_NOTAS.md` § Onde estamos** (decisão de 2026-10-18,
  `PLANO.md` M4). Esta seção guarda o que vale entre sprints. Sprint 1 aberta (Etapa A, teste no MacBook).
- **Última atualização:** 2026-10-18, Opus 5.5 (Claude Code, MacBook Air): máquina decidida e melhorias M1–M4.
- **Máquina (Leonardo, 2026-10-18):** só o i7 fica ligado, com Debian 12 direto e cada serviço no seu Docker
  Compose (sem Proxmox); o i5 desliga depois da Fase 1c do `PLANO.md`. Sem backup do banco por enquanto. Motivo: conta de luz.

## Histórico

### 2026-10-16 — Fase 0 (Opus 5.5, no app do Claude)

**Decisões tomadas nesta sessão**
- Arquitetura mudou para a "mescla": o app do Claude (iPhone/Mac/web) é a porta de entrada,
  conectado a um servidor MCP em casa como conector personalizado. Os dados (banco, vault,
  documentos) ficam em casa; o modelo é só o cérebro. Qualquer outro cliente MCP (ex.: ChatGPT)
  conecta igual.
- Exposição pela internet: **Tailscale Funnel** (grátis, sem domínio). Cloudflare Tunnel ficou
  como alternativa no compose (`--profile cloudflare`).
- Login: OAuth via **GitHub ou Google** (`AUTH_PROVEDOR`), com lista de permitidos.
- Não usar gateway MCP de terceiros: o próprio FastMCP junta tudo num endpoint só.
- Paperless: `paperless-mcp` (PyPI). O `paperless-ngx-mcp` (npm) foi testado e é incompatível
  com o SDK MCP do FastMCP 4 — descartado.
- Vault: `@bitbonsai/mcpvault` (npm).
- WhatsApp fica para depois (fase 6), com número/celular dedicado; API própria tipo WAHA,
  Telegram e Discord são a segunda etapa (fase 8).
- Teste primeiro no MacBook, produção depois no i7.

**O que mudou em relação ao plano anterior (modo antigo)**
- Antes: gateway próprio + Claude Code headless + WhatsApp/Telegram como entrada, só rede local.
  Agora: app do Claude como entrada, endpoint MCP exposto com login. O gateway volta na fase 6.
- Antes: vault acessado direto pelo Claude Code. Agora: via MCP pronto (mcpvault).
- O scaffolding antigo (feito na máquina do trabalho) **não** foi aproveitado; este repo começou do zero.

**O que foi construído**
- `servidor/assistente/banco.py`: ferramentas `registrar_gasto`, `consultar_gastos`,
  `listar_categorias_gasto`, `registrar_ponto`, `consultar_ponto` (horas com desconto de pausas),
  `registrar_atividade`, `consultar_atividades`, `desfazer_registro`, `consultar_auditoria`.
- Dois usuários de banco: leitura (só SELECT) e escrita (sem DELETE; auditoria só INSERT) —
  verificado em Postgres real.
- `servidor/assistente/auth.py`: login GitHub (por login) ou Google (por e-mail verificado).
- `servidor/assistente/servidor.py`: endpoint único; monta banco + proxies de Paperless e vault;
  `BLOQUEADAS` desliga ferramentas perigosas das peças prontas (link público, apagar nota etc.).
- Migração inicial Alembic (`0001`), `docker-compose.yml`, `.env.example`, README, PLANO, IMPLANTACAO.
- `NOME_USUARIO` e `PORTA_HOST` permitem uma segunda instância (esposa) na mesma máquina.

**Pendências / em aberto**
- Build Docker e o fluxo OAuth real com o claude.ai ainda não foram testados (Etapa A).
- Confirmar que o Tailscale Funnel funciona na versão do app instalada no Mac.
- Inventário completo de todas as máquinas (ver abaixo).
- E-mail: Gmail via conector nativo já; ferramenta própria multi-conta na fase 4b
  (Hotmail exige OAuth2; corporativo depende da política da corporação).
- Ligação pela operadora: ideia sem data.

---

## O que já se sabe (dito pelo Leonardo, ainda não conferido nas máquinas)

**Máquinas**
- **i7-6700**, 16 GB DDR4, SSD SATA 240 GB, sem GPU → produção, Debian 12 direto (decisão de 2026-10-18): o
  assistente e, depois, os serviços que vêm do i5, cada um no seu Docker Compose.
- **i5-3330**, 16 GB, SSD SATA 240 GB + HD 500 GB, sem GPU → roda Proxmox com a VM do atendente de
  WhatsApp (projeto comercial à parte, em Python) e uma VM de serviços de rede. WireGuard já
  configurado ali, parado desde a mudança de casa. Vai ser desligado (2026-10-18): os serviços vão para o i7.
- Um segundo HD de 500 GB está livre. Compra armazenamento se precisar.
- **MacBook**: ambiente de teste (Etapa A).

**Premissas que guiam as decisões**
- Não pagar nada além do que já paga (plano Pro do Claude). Por isso Tailscale e não domínio.
- O servidor é particular justamente para guardar dados sensíveis, inclusive de trabalho, sob controle dele.
- Quer registrar tudo o que for possível; ferramentas e categorias novas surgem com o uso.
- Evolução do banco dirigida pelo uso: quando ele pedir para registrar algo que não existe, um
  modelo competente cria modelo + migração Alembic + ferramentas (ver "Dado novo" no README).
- Execução por modelos: um modelo superior estrutura cada fase, um modelo competente executa cada tarefa.

**Peças que já existem fora deste repo**
- Vault do Obsidian particular, já no modelo "contexto no vault, números no banco", com uma
  prévia de estrutura que ele quer manter ou melhorar. Será migrado para o servidor (fase 2).
- Documento antigo "Assistente Pessoal de IA — Projeto de Implementação" (Claude Docs): era o
  plano vivo do modo antigo. **Este repo passa a ser a fonte da verdade.**
- Ele já usou o **Jev** (TypeSafe AI) como seletor de modelo; entra no gateway do WhatsApp (fase 6).

**Ideias futuras (sem data, só registro)**
- Monitor de rede em casa: ver o que é acessado, consumo, bloquear pelo agente.
- Centralizar o acesso às câmeras de monitoramento.
- Ligação pela operadora (alerta por voz).

---

## Inventário das máquinas (fazer em casa)

Juntar as especificações de **todas** as máquinas e salvar no vault (e um resumo em
`docs/inventario.md`). Para cada máquina:
- Identificação: modelo, função atual, sistema operacional e versão, hostname, IP
- CPU, RAM (quantidade, tipo, slots livres), GPU
- Discos: modelo, capacidade, tipo (SSD/HD), uso, partições, **saúde SMART**
  (`smartctl -a /dev/sdX`: horas ligado, setores realocados/pendentes, desgaste do SSD)
- Rede: interfaces, velocidade
- Serviços/VMs rodando (Proxmox: lista de VMs e recursos de cada uma)
- Observações: defeitos, upgrades possíveis

Comandos úteis (Linux): `lsblk -o NAME,SIZE,MODEL,ROTA,TYPE,MOUNTPOINT`, `sudo smartctl -a /dev/sdX`,
`lscpu`, `free -h`, `sudo dmidecode -t memory`, `ip -br a`, `qm list` (Proxmox).
No Mac: `system_profiler SPHardwareDataType SPStorageDataType`.

---

## Regra de passagem (levar também para o vault)

Vale para todo projeto longo dividido em fases, executado por modelos diferentes:

1. **Ao começar:** ler este arquivo de contexto inteiro antes de qualquer coisa.
2. **Ao terminar uma fase ou tarefa,** o modelo que executou atualiza o arquivo de contexto com:
   - o que foi feito (arquivos, comandos, resultados de teste);
   - o que mudou em relação ao plano e por quê;
   - decisões tomadas e alternativas descartadas;
   - pendências, problemas abertos e o que não foi testado;
   - o estado atual (fase, data, modelo).
3. **E escreve o prompt para o próximo modelo** rodar a etapa seguinte, completo e autossuficiente:
   objetivo, arquivos a ler, critério de pronto, restrições e qual modelo é o indicado.
4. Nada importante fica só na conversa: se foi decidido, vai para o arquivo.

---

## Prompt para a próxima etapa

Enquanto houver sprint aberta, o prompt de abertura e o passo atual ficam em `SPRINT.md`
(§ Prompt de abertura) e `SPRINT_NOTAS.md` (§ Onde estamos). A "Regra de passagem" acima já
foi levada para o vault em 2026-10-16 (`40-regras/programacao/registro-temporario-de-sprint-na-raiz.md`).
