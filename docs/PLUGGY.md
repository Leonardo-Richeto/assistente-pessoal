# Pluggy: conta, conector e chaves

Passo a passo para o worker de gastos (Ficha 10) ler o banco do Leonardo pelo Meu Pluggy. Feito de verdade em
2026-10-27 (Nubank). Conferido também em `pluggy.ai/meu-pluggy` e `github.com/pluggyai/meu-pluggy`.

**São duas plataformas.** O **Meu Pluggy** (meu.pluggy.ai) guarda a conexão com o banco. O **dashboard**
(dashboard.pluggy.ai) dá as chaves da API. A Demo do dashboard liga uma à outra: ela conecta a sua conta do Meu
Pluggy (não o banco direto) à sua aplicação, e só então a API enxerga o banco. Grátis para uso pessoal, sem prazo,
até 5 conexões do mesmo titular. O aviso de trial de 15 dias e o botão de produção ("falar com vendas") são da parte
comercial: não precisa.

## 1. Meu Pluggy (o lado do banco)

1. Abra `https://meu.pluggy.ai` e crie a conta.
2. Clique no botão principal de conectar, ache o banco e autorize no app do banco (Open Finance).
3. Repita para cada banco: conta corrente e cartão de crédito vêm juntos, por banco.
4. Confira no Meu Pluggy se as transações aparecem. Os dados atualizam uma vez por dia.

O código no link da conexão do Meu Pluggy (`meu.pluggy.ai/connections/<código>`) **não** é o Item ID: a API dá 404.

## 2. Dashboard (o lado do desenvolvedor)

1. Abra `https://dashboard.pluggy.ai`, crie a conta e um time.
2. Em **Aplicações**, crie uma aplicação. Cada aplicação tem o seu **Client ID** e o seu **Client Secret**: as
   chaves do `.env` têm de ser da aplicação onde a conexão do passo 3 foi feita (com as de outra aplicação, 404).
3. Não cole o Client ID e o Client Secret no chat.

## 3. Ligar o Meu Pluggy à aplicação

1. Na linha da aplicação, clique no **▶** (Demo).
2. Escolha o conector **MeuPluggy** (não o banco, o Sandbox nem o Pluggy Bank) e entre com a conta do Meu Pluggy.
3. Faça isso uma vez **por banco** conectado no Meu Pluggy.
4. Em cada conexão, abra o menu de três pontos no canto e clique em **Copiar Item ID**.
5. Confira no Mac (não grava nada): `cd servidor && PYTHONPATH=. uv run python -m assistente.workers.pluggy --item <id>`.
   Esperado: `"conector": "MeuPluggy", "status": "UPDATED"`.

## 4. Chaves no `.env`

No Mac (teste), no `.env` da raiz do repo. No i7, no `.env` de `/srv/assistente`. Edite o arquivo você mesmo.

```
PLUGGY_CLIENT_ID=<client id>
PLUGGY_CLIENT_SECRET=<client secret>
PLUGGY_ITEM_IDS=<item id do banco 1>,<item id do banco 2>
```

O `.env` fica fora do git. Com o cofre no ar (Ficha 11), a cópia oficial das chaves vai para ele; a de uso continua
no `.env` (o worker nunca lê o cofre).

## 5. No i7 (deploy)

Antes, no Mac: commit e push. Depois, no i7:

Primeiro o código, com o worker ainda desligado (o perfil `pluggy` fora):

```bash
cd /srv/assistente/app && git pull
docker compose up -d --build && bash scripts/verificar.sh
```

Depois, quando o Item ID do MeuPluggy existir. Só sobe o serviço `workers`: o servidor e o Funnel não caem.

```bash
nano /srv/assistente/.env   # as 3 linhas PLUGGY_ e COMPOSE_PROFILES=tailscale,pluggy
cd /srv/assistente/app && docker compose up -d --build workers
docker compose logs --tail 20 workers   # esperado: "pluggy: N novos, 0 já existiam, ... (primeira)"
```

- A migração 0007 roda sozinha no `up -d --build`, antes do servidor e do worker.
- O `up -d --build` recria o servidor e o `tailscale`: o Funnel pode levar até ~20 min para voltar. Espere, não
  recrie de novo.
- A instância da Nathalia não ganha o perfil `pluggy`; o `git pull` dela só leva a migração.
- Depois do deploy, cole de novo no Projeto "Assistente" o texto da Ficha 1 (ganhou a seção "Gastos do banco").

## 6. Renovação

- O consentimento do Open Finance vence (em geral, 12 meses). Renove no Meu Pluggy quando o banco pedir.
- Se o Item ID mudar (conexão refeita), troque em `PLUGGY_ITEM_IDS` e reinicie o serviço `workers`.
- Se o `contexto_inicial` avisar "Pluggy sem sincronizar", veja primeiro se o consentimento venceu.
