# Backup e migração do servidor

O servidor sai de uma máquina e sobe em outra, inclusive em outra rede, em cerca de 30 minutos e
sem perder dados. Backup e migração são o mesmo processo: o pacote do backup diário é o mesmo que
alimenta a migração. Plano original: "Plano de Portabilidade do Servidor" (Leonardo, 2026-10-19).

## Regras

1. Código no git (`<home>/app`); todo o estado numa pasta só (`<home>`, `ASSISTENTE_HOME` no `.env`).
2. Nada amarrado à máquina: sem IP fixo, sem caminho absoluto no código, preparo da máquina por script.
3. Nada amarrado à rede: a entrada é o nó Tailscale `TS_NOME` (container), com a mesma URL em qualquer rede.
4. Banco sai por `pg_dump -Fc`, nunca como cópia de `data/postgres`. Tudo o que sai vai cifrado com `age`.
5. A chave privada do `age` nunca fica no servidor: gerenciador de senhas e uma cópia impressa.

```
<home>/                  (/srv/assistente no i7)
├── app/                 git clone deste repositório (descartável)
├── .env                 configuração e senhas (fora do git)
├── data/
│   ├── postgres/        dados internos do Postgres (NUNCA copiar entre máquinas)
│   ├── paperless/       reservado para a Fase 2
│   ├── tailscale/       identidade do nó Tailscale
│   ├── sessoes/oauth/   clientes e tokens do login (cifrados com a JWT_SIGNING_KEY)
│   └── vault-versoes/   versões do Syncthing (não entram no pacote)
├── vault/               vault do Obsidian (git + Syncthing)
├── backups/             pacotes do exportar.sh
└── logs/
```

## Scripts

| Script | O que faz |
|---|---|
| `scripts/preparar_host.sh` | Debian 12 ou 13: Docker, git, age, Tailscale do host (só SSH), Syncthing, árvore de `<home>`, link `app/.env`, timer do backup |
| `scripts/exportar.sh` | Para quem grava (o Postgres fica), gera dump, contagens, vault, sessões, Tailscale, `.env`, `manifesto.json` e `SHA256SUMS`, e cifra tudo em `assistente-AAAAMMDD-HHMM.tar.age` (+ `.sha256`). Religa os serviços no fim, menos com `--congelar` |
| `scripts/importar.sh` | Na máquina nova: confere o hash, decifra, confere cada arquivo, põe o `.env` (com o `ASSISTENTE_HOME` novo), sobe só o Postgres, restaura, confere as contagens, `alembic upgrade head`, vault e sessões no lugar, sobe tudo e roda o `verificar.sh` |
| `scripts/verificar.sh` | Serviços saudáveis, migração com código 0, schema, contagens (se receber o arquivo), consulta de leitura pelas ferramentas MCP, migração do banco na cabeça, tabelas novas legíveis, vault (pasta, notas indexadas, `.git` gravável, `index.lock`, `filter=`; `AVISO` não reprova; `python -m assistente.verificacao --sem-banco --sem-http` roda só o vault), `/mcp` sem token = 401 e, com o perfil `tailscale`, o Funnel respondendo 401 |

Os scripts rodam em Linux, macOS e Windows (Git Bash). Sem `age` no host, usam a imagem
`deploy/ferramentas` (Alpine + age, versões fixas). Recusam: `.env` sem alguma variável do
`.env.example`, obrigatória vazia, `ASSISTENTE_HOME` diferente da pasta do `.env`, e importar por cima
de `data/postgres`, banco, vault ou `data/tailscale` com conteúdo. Nada é apagado.

## Chave do age (uma vez, fora do servidor)

```bash
age-keygen -o identidade-assistente.txt         # ou: docker run --rm assistente-ferramentas:age-1.3.2 age-keygen
```

Guarde o arquivo inteiro no gerenciador de senhas e imprima uma cópia. Ponha só a linha
`# public key: age1...` no `.env`, como `AGE_DESTINATARIO=age1...`. Sem a identidade, nenhum
pacote abre: se ela se perder, os backups viram lixo.

## Backup diário

`preparar_host.sh` instala `assistente-backup.timer` (03:15) rodando `scripts/exportar.sh --retencao`.
O timer só é ligado com `AGE_DESTINATARIO` preenchido; preencha e rode o script de novo.

- Destino: `BACKUP_DESTINO` no `.env` (vazio = `<home>/backups`, mesmo disco: não protege contra perda
  do disco). Aponte para o HD externo montado.
- Retenção: o mais novo de cada um dos 7 últimos dias e de cada uma das 4 últimas semanas ISO (como
  `restic --keep-daily 7 --keep-weekly 4`). Só arquivos com o nome exato do exportar são apagados.
- O servidor fica parado durante o dump (segundos) e volta sozinho, mesmo se o backup falhar.
- Conferir: `systemctl list-timers assistente-backup.timer` e `journalctl -u assistente-backup -n 30`.

## Formas de transferência

O pacote é sempre o mesmo `.tar.age` com o `.sha256` ao lado.

| Situação | Caminho |
|---|---|
| Mesma rede local | `rsync -a <pacote>* <usuario>@<maquina-nova>:<home>/backups/` |
| Redes diferentes, as duas ligadas | o mesmo `rsync` pelo nome da tailnet do host novo (sem abrir portas) |
| Antiga desligada ou sem internet | HD externo: o pacote já sai cifrado |
| Antiga perdida (defeito, roubo) | último pacote do `BACKUP_DESTINO` |

Nuvem pública não é caminho padrão. Se um dia for, só o `.tar.age`.

## Procedimento de migração (~30 min)

1. **Máquina nova:** instalar o Debian, clonar em `<home>/app`, `sudo bash <home>/app/scripts/preparar_host.sh`,
   sair e entrar de novo (grupo `docker`), `sudo tailscale up --hostname=<nome-do-host>` (nó do host, só SSH).
2. **Congelar a antiga:** `bash scripts/exportar.sh --congelar`. Dali em diante nada é gravado nela.
3. **Transferir** o pacote e o `.sha256` (tabela acima) e a identidade do age (pendrive ou digitada; não deixe
   na máquina depois).
4. **Importar:** `bash scripts/importar.sh <home>/backups/<pacote>.tar.age --chave <identidade.txt>`.
   Ele só termina com 0 se o `verificar.sh` passar. Apague a identidade da máquina nova no fim.
5. **Trocar a identidade do Tailscale**, de um destes dois jeitos:
   - **Assumir a da antiga** (mesmo nó, mesma URL, sem mexer no painel): desligue o container da antiga
     (`docker compose --env-file ../.env down` lá, ou a máquina) **antes** e importe com `--assumir-tailscale`.
     As duas com o mesmo estado ao mesmo tempo brigam pelo nó.
   - **Nó novo** (padrão do importar): ponha uma `TS_AUTHKEY` nova no `.env`, apague o nó antigo no painel,
     suba (`docker compose --env-file ../.env up -d`) e, se o painel tiver posto sufixo (`assistente-1`), renomeie
     para `TS_NOME`. Ligue o Funnel e desligue o key expiry para o nó novo no painel.
6. **Reautenticar** o que pedir (lista abaixo) e testar pelo app do Claude: uma consulta e um registro.
   Rode `bash scripts/verificar.sh` de novo (agora com o Funnel).
7. **Manter a antiga desligada por 7 dias**, sem apagar nada. Depois, apagar os discos.

### Reautenticações possíveis

- Conector no app do Claude: nada, se a URL (`TS_NOME`) for mantida e a `JWT_SIGNING_KEY` vier no `.env`
  do pacote (ela decifra `data/sessoes/oauth`). Com `--manter-env` e outra chave, reconectar.
- Google OAuth (login): nada; a URL de callback é a mesma.
- Claude Code headless (Fase 6): `claude login` com o plano Pro.
- Google Calendar e Gmail próprios (Fases 4 e 4b): só se o token copiado for recusado.
- WhatsApp (Fase 6): parear de novo pelo QR se a sessão não subir.
- Pluggy e OpenAI: nada, são chaves no `.env`.

## Ensaio

`bash scripts/testes/ensaio_migracao.sh <pasta-vazia>` monta uma origem com dados **sintéticos** (sem
Tailscale), exporta com `--congelar`, derruba a origem e importa num destino na mesma máquina. Passa se o
importar (com o verificar) passar e o vault e as contagens forem iguais. `bash scripts/testes/test_retencao.sh`
testa a retenção sem Docker. Ensaio mensal de restauração: rodar o `importar.sh` com o último pacote numa
máquina ou VM descartável.

## Limites conhecidos

- **Paperless:** a exportação e a importação (`document_exporter`/`document_importer`) ainda não existem. Os
  dois scripts param com erro se o compose tiver um serviço `paperless`. Implementar junto com a Fase 2.1.
- **Mac de teste (layout antigo):** os dados de lá estão nos volumes nomeados do compose antigo, que o compose
  novo não usa (depois do `git pull`, o Mac sobe com banco vazio; o volume antigo continua lá, intacto). Para
  levar os registros: com a stack antiga de pé, `git show 8d2ec8d:deploy/backup-banco.sh > /tmp/backup-banco.sh`,
  `BACKUP_DIR=~/backup-mac bash /tmp/backup-banco.sh`, e no i7 `deploy/restaurar-banco.sh` num banco novo,
  conferir e adotar como no B10 (`docs/IMPLANTACAO.md`). Ou começar limpo. O login do Mac não vem: a URL muda.
- **Tailscale em container:** só validado com `docker compose config`; nunca subiu (o teste foi numa máquina
  sem Tailscale). Conferir no i7: `/healthz`, o Funnel e o IP real no log do limite (`assistente.limite`).
- **ARM → x86:** o dump lógico não depende da arquitetura, mas a passagem Mac → i7 ainda não foi feita.
