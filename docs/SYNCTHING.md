# Vault: Syncthing e commit diário

Roteiro do Leonardo. A produção (o i7) é o **nó central**: ela guarda o vault em
`/srv/vault`, faz o commit diário e é a única que fala com o GitHub. Mac, PC Windows e iPhone
sincronizam com ela. Decisões: D10 (nada pago além do Pro), D15 (só a produção comita).

Pré-requisito: `deploy/preparar-maquina.sh` já rodou (Syncthing instalado, `/srv/vault` criada).
Troque `<usuario>` pelo seu usuário na produção e `<maquina>` pelo nome dela na tailnet.

## Regras que não mudam

- Só a produção comita. Nunca dois aparelhos comitando o mesmo vault.
- O `.git` nunca viaja pelo Syncthing (está no `.stignore`).
- A GUI do Syncthing da produção fica só em `127.0.0.1:8384`. Nunca no Funnel, nunca em `0.0.0.0`.
- Edição simultânea do mesmo arquivo vira `nome.sync-conflict-AAAAMMDD-HHMMSS-XXXX.md`.
  Nada se perde. Abra os dois, junte à mão e apague o `.sync-conflict-*`.
- O `.stignore` **não** é sincronizado. Cada aparelho precisa do seu (seção 4).

## 1. Syncthing na produção

```bash
sudo systemctl enable --now syncthing@$USER
systemctl status syncthing@$USER      # deve estar "active (running)"
```

A GUI já nasce em `127.0.0.1:8384`. Confira que não abriu para fora:

```bash
ss -ltn | grep 8384                        # deve mostrar 127.0.0.1:8384, não 0.0.0.0
```

Se mostrar `0.0.0.0`, pare: abra a GUI pelo túnel, vá em Ações → Configurações → GUI e deixe
o endereço `127.0.0.1:8384`.

Acesse a GUI do seu computador por túnel SSH (pelo nome da tailnet, se já tiver o Tailscale). Usamos a porta local 18384 para não colidir com o Syncthing do Mac, que já usa a 8384:

```bash
ssh -L 18384:127.0.0.1:8384 <usuario>@<maquina>
# deixe aberto e visite http://127.0.0.1:18384 no navegador
```

Na primeira visita:

1. Defina usuário e senha da GUI (Ações → Configurações → GUI). Senha forte, só sua.
2. Desligue "Anonymous Usage Reporting" se aparecer.
3. Anote o **ID do dispositivo** da produção (Ações → Mostrar ID).
4. Apague a pasta "Default Folder", que o Syncthing cria sozinho.

## 2. Primeiro sync: levar o vault atual para `/srv/vault`

Objetivo: o vault de hoje (Mac, `~/Desktop/Projetos/Obsidian`, com `.git` e GitHub privado)
aparece em `/srv/vault` sem duplicar e sem conflito. Receita: a produção **clona** o repositório
do GitHub (fica com o `.git`); o Mac **aponta o Syncthing para a pasta que já existe**, com o mesmo
conteúdo. Arquivos idênticos não geram conflito.

**No Mac, antes de tudo** (o GitHub precisa estar igual à pasta):

```bash
cd ~/Desktop/Projetos/Obsidian
git status            # precisa estar limpo; se não, comite
git push
git log -1 --oneline  # anote o hash
```

Feche o Obsidian no Mac durante o primeiro sync.

**Na produção.** O repositório é privado, então precisa de credencial. Recomendado: chave de deploy,
nesta ordem.

1. Gere a chave:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/vault_deploy -N ""
   cat ~/.ssh/vault_deploy.pub
   ```
2. No GitHub: repositório do vault → Settings → Deploy keys → Add deploy key → cole a chave.
   Marque **Allow write access** se for usar `VAULT_PUSH=1` (seção 5); sem push, deixe só leitura.
3. Clone. `/srv/vault` já existe, vazia (o `preparar-maquina.sh` criou); o clone para pasta vazia funciona.
   Clone **antes** de adicionar a pasta no Syncthing, que cria o `.stfolder` e deixaria a pasta não vazia.
   ```bash
   GIT_SSH_COMMAND='ssh -i ~/.ssh/vault_deploy -o IdentitiesOnly=yes' \
     git clone git@github.com:<conta>/<repositorio-do-vault>.git /srv/vault
   git -C /srv/vault config core.sshCommand 'ssh -i ~/.ssh/vault_deploy -o IdentitiesOnly=yes'
   git -C /srv/vault log -1 --oneline    # tem de ser o mesmo hash do Mac
   ```
   Se o clone recusar por pasta não vazia, não apague nada: pare e confira o que há nela.
4. `.gitignore` do vault (defesa para o commit diário não levar `.stversions`, `.stfolder` e temporários).
   O comando acrescenta ao arquivo que já existir, sem sobrescrever:
   ```bash
   cat /srv/assistente/deploy/vault/gitignore-do-vault >> /srv/vault/.gitignore
   ```
   O primeiro `systemctl start vault-commit.service` (seção 5) comita esse arquivo.

**Pasta no Syncthing da produção:**

1. GUI → Adicionar pasta. Rótulo `vault`, ID `vault`, caminho `/srv/vault`.
2. Aba Compartilhamento: marque os aparelhos (depois da seção 3).
3. Aba **Versionamento de arquivos**: **Staggered**, "Maximum Age" 30 dias (`2592000` s) e
   **"Versions Path" = `/srv/vault-versoes`** (crie antes: `sudo install -d -o "$USER" -g "$USER" /srv/vault-versoes`).
   Esta é a rede de segurança contra apagar ou sobrescrever por engano. As versões ficam **fora**
   do vault de propósito: assim a busca do assistente não acha notas velhas e o git não as vê.
   (O `.gitignore` e o `commit-diario.sh` também ignoram `.stversions` por defesa.)
4. Aba Avançado: "Tipo de pasta" = **Send & Receive** (padrão). "Watch for Changes" ligado.
5. Aba **Ignorar padrões**: cole o conteúdo de `deploy/vault/.stignore` (seção 4) **antes de salvar**,
   no próprio diálogo "Adicionar pasta". Depois de salvar, a primeira varredura já usa os padrões.

## 3. Conectar os aparelhos

Em cada aparelho: instalar, anotar o ID dele, adicioná-lo na produção (e a produção nele).
Dentro da tailnet o Syncthing acha a produção sozinho; se não achar, no aparelho edite a
produção e ponha o endereço `tcp://<maquina>:22000` (nome da tailnet).

### Mac

- Opção A: Syncthing para macOS (app de barra de menu, `brew install --cask syncthing-app` ou o
  site oficial syncthing.net → Downloads → macOS). GUI em `http://127.0.0.1:8384`.
- Opção B: **Synctrain** (App Store, mesmo app do iPhone, código aberto).

Adicione a pasta apontando para a pasta existente `~/Desktop/Projetos/Obsidian`, com o mesmo ID
`vault`, tipo **Send & Receive**, versionamento Staggered também (é grátis e protege o Mac; deixe o caminho de versões padrão ou fora da pasta). Cole o `.stignore` na aba Ignorar padrões **antes de salvar**. O Mac
vai comparar com a produção, achar tudo igual e só reconciliar. Espere o status "Atualizado".

**O `.git` do Mac (D15).** O Mac deixa de comitar o vault. Depois do primeiro sync completo:

1. Desligue o plugin Obsidian Git no Mac, se existir.
2. Mova o `.git` para **fora** da pasta do vault, sem apagar: `mv ~/Desktop/Projetos/Obsidian/.git ~/vault-git-mac-parado`.
   Reverter é mover de volta. Não deixe a cópia dentro do vault: ela seria sincronizada e comitada.

Se deixar o `.git` ativo, ele diverge do da produção e o próximo `git pull` vira bagunça.

### PC Windows

Syncthing oficial: baixe em syncthing.net (Windows, 64 bits) ou `winget install Syncthing.Syncthing`.
Para iniciar com o Windows e ter ícone de bandeja, use o **SyncTrayzor v2**.

**SyncTrayzor original está sem manutenção.** Conferido em 2026-10-17: o repositório `canton7/SyncTrayzor`
foi arquivado em 2025-08-24, com o aviso "SyncTrayzor is unmaintained". O README recomenda o fork
`SyncTrayzor v2` (de GermanCoding). Confira você mesmo antes de instalar, ou use só o Syncthing oficial
com a tarefa de iniciar no login. Alternativa com manutenção: Syncthing Tray.

Crie a pasta em um caminho curto (ex.: `C:\Vault`), ID `vault`, Send & Receive, e cole o `.stignore` na aba Ignorar padrões antes de salvar.
Ative "Ignorar permissões" na pasta (Avançado), porque o Windows não tem permissões de arquivo Unix.

### iPhone: Synctrain

**Synctrain** (App Store, gratuito, código aberto, licença MPL 2.0). Decisão D10: não pagar app de sync.
No iPhone as pastas ficam na pasta do app, visível no app Arquivos.

1. Instale, abra, anote o ID do dispositivo, adicione na produção.
2. Aceite a pasta `vault` que a produção compartilha.
3. No Obsidian do iPhone, abra a pasta como vault (Abrir pasta como cofre, no app Arquivos).

Não testei o item 3 porque não tenho o iPhone, nem se o Synctrain aceita padrões de ignorar (`.stignore`). Se não aceitar, o iPhone sincroniza também `.obsidian/workspace*.json` e temporários; o efeito é só conflito de layout. Se o Obsidian não aceitar a pasta do Synctrain,
avise: o plano B é outra forma de abrir (a decisão fica com você). O iOS limita o sync em segundo plano:
abra o Synctrain antes de abrir o Obsidian para ele atualizar.

Em todos os aparelhos, em Ações → Configurações, deixe só o necessário: "Local Discovery" ligado em
casa, "NAT Traversal" e "Relaying" a seu critério. Com Tailscale ligado nos aparelhos, o caminho
direto pela tailnet evita relays públicos.

## 4. Padrões de ignorar (`.stignore`)

Copie o arquivo do repositório para a raiz da pasta sincronizada **em cada aparelho**:

```bash
cp /srv/assistente/deploy/vault/.stignore /srv/vault/.stignore    # na produção
```

No Mac/Windows/iPhone, cole o conteúdo na aba "Ignorar padrões" da pasta (mesmo efeito). Ele ignora
`.git`, `.obsidian/workspace*.json`, `.trash`, temporários e lixo de macOS e Windows.

## 5. Commit diário na produção

Roda às 03:30, só comita se houver mudança, com mensagem datada. Não apaga nada.

```bash
sudo cp /srv/assistente/deploy/vault/vault-commit.service /etc/systemd/system/
sudo cp /srv/assistente/deploy/vault/vault-commit.timer   /etc/systemd/system/
sudo sed -i "s/<usuario>/$USER/" /etc/systemd/system/vault-commit.service
sudo systemctl daemon-reload
sudo systemctl enable --now vault-commit.timer
systemctl list-timers vault-commit.timer
```

Teste na hora, sem esperar a madrugada:

```bash
sudo systemctl start vault-commit.service
journalctl -u vault-commit.service -n 20 --no-pager
```

**Push para o GitHub** (decisão de manter o GitHub por enquanto). Só liga com a chave de deploy
com escrita (seção 2). Crie o arquivo de ambiente:

```bash
echo 'VAULT_PUSH=1' | sudo tee /etc/default/vault-commit
```

Sem esse arquivo (ou sem o `1`), o serviço só comita localmente. Teste outra vez com
`systemctl start` e confira no journal a linha "push feito".

**Lint diário** (`PLANO.md` M3). Roda às 03:40, depois do commit, o `90-meta/lint-do-vault.py` do próprio
vault. Só lê. O relatório fica em `/srv/vault-lint/ultimo.md`, fora do vault, para não entrar no commit:

```bash
sudo install -d -o "$USER" -g "$USER" /srv/vault-lint
sudo cp /srv/assistente/deploy/vault/vault-lint.service /etc/systemd/system/
sudo cp /srv/assistente/deploy/vault/vault-lint.timer   /etc/systemd/system/
sudo sed -i "s/<usuario>/$USER/" /etc/systemd/system/vault-lint.service
sudo systemctl daemon-reload && sudo systemctl enable --now vault-lint.timer
sudo systemctl start vault-lint.service; cat /srv/vault-lint/ultimo.md | head -20
```

Com ERRO no vault, o serviço fica como falho (`systemctl --failed` mostra). Corrija a nota e rode de novo.
AVISO não marca falha.

## 6. Apontar o assistente para o vault

No `.env` de `/srv/assistente`:

```
VAULT_PATH=/srv/vault
```

Depois:

```bash
cd /srv/assistente && docker compose up -d
```

O compose monta `/srv/vault` em `/vault` dentro do container. Confira no app: peça "liste as pastas do
vault". O container roda com uid 1000, igual ao primeiro usuário do Debian. Confira com `id -u`: se der 1000, a escrita funciona. Se for outro uid e aparecer erro de permissão ao criar
nota, veja `docker compose logs servidor` e avise antes de mudar `chown` ou `chmod`.

## 7. Conferir que funciona

1. Crie uma nota no Mac. Ela aparece em `/srv/vault` em segundos (`ls -lt /srv/vault | head`).
2. Peça ao Claude para criar uma nota em `00-inbox`. Ela aparece no Mac e no iPhone.
3. Apague uma nota de teste no Mac. Ela some da produção e sobra uma cópia em `/srv/vault/.stversions`.
4. Na manhã seguinte, `git -C /srv/vault log --oneline | head` mostra o commit das 03:30.

## Se algo der errado

- Apareceu `.sync-conflict-*`: junte à mão e apague o arquivo de conflito.
- Syncthing "Desatualizado" por muito tempo: veja se o outro aparelho está ligado e na tailnet.
- Apagou nota por engano: recupere de `.stversions` (produção) ou do `git` (`git -C /srv/vault checkout -- <arquivo>`).
- Dois aparelhos comitaram: pare, não force push, e peça ajuda antes de mexer.
