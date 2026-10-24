# Vault: Syncthing e commit diário

Roteiro do Leonardo. A produção (o i7) é o **nó central**: ela guarda o vault em
`/srv/assistente/vault`, faz o commit diário e é a única que fala com o GitHub. Mac, PC Windows e iPhone
sincronizam com ela. Decisões: D10 (nada pago além do Pro), D15 (só a produção comita).

Pré-requisito: `scripts/preparar_host.sh` já rodou (Syncthing instalado, `/srv/assistente/vault` criada).
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

## 2. Primeiro sync: levar o vault atual para `/srv/assistente/vault`

Objetivo: o vault de hoje (Mac, `~/Desktop/Projetos/Obsidian`, com `.git` e GitHub privado)
aparece em `/srv/assistente/vault` sem duplicar e sem conflito. Receita: a produção **clona** o repositório
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
3. Clone. `/srv/assistente/vault` já existe, vazia (o `preparar_host.sh` criou); o clone para pasta vazia funciona.
   Clone **antes** de adicionar a pasta no Syncthing, que cria o `.stfolder` e deixaria a pasta não vazia.
   ```bash
   GIT_SSH_COMMAND='ssh -i ~/.ssh/vault_deploy -o IdentitiesOnly=yes' \
     git clone git@github.com:<conta>/<repositorio-do-vault>.git /srv/assistente/vault
   git -C /srv/assistente/vault log -1 --oneline    # tem de ser o mesmo hash do Mac
   ```
   Não grave `core.sshCommand` na config do repositório: o commit diário ignora a config do `.git` (a pasta
   também é escrita pelo container) e passa a chave sozinho no push, de `~/.ssh/vault_deploy` ou do caminho em
   `VAULT_SSH_CHAVE` (seção 5).
   Se o clone recusar por pasta não vazia, não apague nada: pare e confira o que há nela.
4. `.gitignore` do vault (defesa para o commit diário não levar `.stversions`, `.stfolder`, temporários e o
   `.obsidian/plugins/*/data.json`, onde plugins guardam chave de API).
   O comando acrescenta ao arquivo que já existir, sem sobrescrever:
   ```bash
   cat /srv/assistente/app/deploy/vault/gitignore-do-vault >> /srv/assistente/vault/.gitignore
   ```
   O primeiro `systemctl start vault-commit.service` (seção 5) comita esse arquivo.

**Pasta no Syncthing da produção:**

1. GUI → Adicionar pasta. Rótulo `vault`, ID `vault`, caminho `/srv/assistente/vault`.
2. Aba Compartilhamento: marque os aparelhos (depois da seção 3).
3. Aba **Versionamento de arquivos**: **Staggered**, "Maximum Age" 30 dias (`2592000` s) e
   **"Versions Path" = `/srv/assistente/data/vault-versoes`** (crie antes: `sudo install -d -o "$USER" -g "$USER" /srv/assistente/data/vault-versoes`).
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
cp /srv/assistente/app/deploy/vault/.stignore /srv/assistente/vault/.stignore    # na produção
```

No Mac/Windows/iPhone, cole o conteúdo na aba "Ignorar padrões" da pasta (mesmo efeito). Ele ignora
`.git`, `.obsidian/workspace*.json`, `.trash`, temporários e lixo de macOS e Windows.

## 5. Commit diário na produção

Roda às 03:30, só comita se houver mudança, com mensagem datada. Não apaga nada.

Antes do commit, o script roda o gitleaks (imagem Docker com versão e digest fixos, sem rede, vault só leitura, config `deploy/vault/gitleaks.toml` do repositório do app, até 15 min por varredura; o `vault-commit.service` para tudo em 30 min) duas vezes:

1. **No que está no stage.** Se ele achar segredo, só os arquivos achados saem do stage (o disco não muda) e o resto é comitado; o journal diz "ERRO: gitleaks achou segredo em: <arquivos>; esses arquivos ficaram fora do commit de hoje". Se o gitleaks falhar, passar do tempo ou o docker não existir, nada é comitado e o stage é desfeito.
2. **Nos commits desde a última varredura limpa** (commits por escrita do servidor, fotos e o commit do dia). O id do último commit varrido fica em `/srv/assistente/logs/vault-commit/ultimo-varrido`, fora do vault; na primeira vez, o histórico inteiro é varrido. **O push só acontece depois desta varredura sair limpa.** Se ela achar segredo, o journal diz "ERRO: gitleaks achou segredo em commits já feitos, nos arquivos: <arquivos>; sem push." Nada é apagado: tire o segredo do histórico (`git filter-repo`, decisão sua) ou, se aceita o risco, grave o id do HEAD naquele arquivo (`git -C /srv/assistente/vault rev-parse HEAD > /srv/assistente/logs/vault-commit/ultimo-varrido`).

Os relatórios (`gitleaks.json` e `gitleaks-commits.json`, em `/srv/assistente/logs/vault-commit/`, modo 600) trazem só arquivo, regra, linha e commit, nunca o valor nem o trecho. Tire o segredo da nota (o valor vai para o cofre; na nota fica `{{segredo:NOME}}`) e rode de novo. Por isso o usuário do `vault-commit.service` precisa estar no grupo `docker` (o `scripts/preparar_host.sh` já põe o `$USER`). O script recusa o dia inteiro se o vault tiver `.gitleaks.toml` ou `.gitleaksignore` na raiz (mesmo como link simbólico), ou um `.gitattributes` (em qualquer pasta) ou `.git/info/attributes` com o atributo `filter`, `diff` ou `binary` (com `-` ou `!` antes, ou `=valor` depois) numa linha que não é comentário (rodariam comando ou esconderiam conteúdo do gitleaks). Comentário com a palavra "diff" e `* text=auto eol=lf` passam.

Se o servidor comitar uma escrita da IA no meio do `git add`, o script tenta o `add` de novo (3 vezes, 2 s entre elas). O push manda o commit **varrido** (não o HEAD, que pode ter andado durante a varredura) para a branch atual no `origin`, só por ssh, com a chave de deploy `~/.ssh/vault_deploy` do usuário do serviço (outro caminho: `VAULT_SSH_CHAVE=/caminho` em `/etc/default/vault-commit`). Sem a chave, o journal diz "ERRO: não achei a chave de deploy" e não há push.

Toda execução sem ERRO, mesmo sem mudança no vault, grava a hora em `/srv/assistente/logs/vault-commit/ultima-execucao-ok` (modo 644). O lint diário avisa "última execução limpa do commit diário há N dias" quando ela passa de 2 dias. Sem esse arquivo (o commit diário nunca rodou limpo), o lint não avisa.

Os serviços rodam em ordem quando os timers disparam juntos (por exemplo, depois de a máquina ficar desligada de madrugada: `Persistent=true`): backup, commit, marcas, lint. É só ordem: a falha de um não impede o outro.

```bash
sudo install -d -o "$USER" -g "$USER" /srv/assistente/logs/vault-commit
sudo cp /srv/assistente/app/deploy/vault/vault-commit.service /etc/systemd/system/
sudo cp /srv/assistente/app/deploy/vault/vault-commit.timer   /etc/systemd/system/
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

Se a chave não está em `~/.ssh/vault_deploy`, acrescente o caminho:
`echo 'VAULT_SSH_CHAVE=/caminho/da/chave' | sudo tee -a /etc/default/vault-commit`. O push usa
`BatchMode=yes` e nunca pergunta: a host key do GitHub precisa estar no `~/.ssh/known_hosts` do usuário (o clone
da seção 2 já gravou).

Sem esse arquivo (ou sem o `1`), o serviço só comita localmente. Teste outra vez com
`systemctl start` e confira no journal a linha "push feito".

**Lint diário** (`PLANO.md` M3). Roda às 03:40, depois do commit, o `90-meta/lint-do-vault.py` do próprio
vault. Só lê. O relatório também lista os arquivos de conflito do Syncthing (`*.sync-conflict-*`) como aviso, sem mudar o código de saída. O relatório fica em `/srv/assistente/logs/vault-lint/ultimo.md`, fora do vault, para não entrar no commit.

As notas marcadas como desatualizadas no banco (`marcar_desatualizada`) entram no relatório como aviso. Quem consulta o banco é o `vault-marcas.service`, às 03:35: ele roda `deploy/vault/marcas-desatualizadas.sh` (`docker compose exec` no container `servidor`) e grava `/srv/assistente/logs/vault-lint/marcas.md`. O lint só lê esse arquivo e nunca chama `docker`: o código do lint vem do vault, pelo Syncthing, e o usuário dele não deve estar no grupo `docker` (docker = root). Falha na consulta vira uma linha de aviso; arquivo com mais de 24 h vira "AVISO: lista de marcas com mais de 24 h."; sem o arquivo, o lint pula a lista. O usuário do `vault-marcas.service` precisa estar no grupo `docker` (o mesmo do backup). Os comandos abaixo ainda põem o mesmo `$USER` nos dois serviços, e o `scripts/preparar_host.sh` põe esse usuário no grupo `docker`: um usuário próprio para o lint, fora do grupo, está pendente (decidir no i7).

```bash
sudo install -d -o "$USER" -g "$USER" /srv/assistente/logs/vault-lint
sudo cp /srv/assistente/app/deploy/vault/vault-lint.service   /etc/systemd/system/
sudo cp /srv/assistente/app/deploy/vault/vault-lint.timer     /etc/systemd/system/
sudo cp /srv/assistente/app/deploy/vault/vault-marcas.service /etc/systemd/system/
sudo cp /srv/assistente/app/deploy/vault/vault-marcas.timer   /etc/systemd/system/
sudo sed -i "s/<usuario>/$USER/" /etc/systemd/system/vault-lint.service /etc/systemd/system/vault-marcas.service
sudo systemctl daemon-reload && sudo systemctl enable --now vault-marcas.timer vault-lint.timer
sudo systemctl start vault-marcas.service; sudo systemctl start vault-lint.service  # nesta ordem
cat /srv/assistente/logs/vault-lint/ultimo.md | head -20
```

Com ERRO no vault, o serviço fica como falho (`systemctl --failed` mostra). Corrija a nota e rode de novo.
AVISO não marca falha.

## 6. Apontar o assistente para o vault

No `/srv/assistente/.env` (o caminho é o de dentro do container; a pasta é sempre `/srv/assistente/vault`):

```
VAULT_PATH=/vault
```

Depois:

```bash
cd /srv/assistente/app && docker compose up -d
```

O compose monta `/srv/assistente/vault` em `/vault` dentro do container. Confira no app: peça "liste as pastas do
vault". O container roda com uid 1000, igual ao primeiro usuário do Debian. Confira com `id -u`: se der 1000, a escrita funciona. Se for outro uid e aparecer erro de permissão ao criar
nota, veja `docker compose logs servidor` e avise antes de mudar `chown` ou `chmod`.

## 7. Conferir que funciona

1. Crie uma nota no Mac. Ela aparece em `/srv/assistente/vault` em segundos (`ls -lt /srv/assistente/vault | head`).
2. Peça ao Claude para criar uma nota em `00-inbox`. Ela aparece no Mac e no iPhone.
3. Apague uma nota de teste no Mac. Ela some da produção e sobra uma cópia em `/srv/assistente/vault/.stversions`.
4. Na manhã seguinte, `git -C /srv/assistente/vault log --oneline | head` mostra o commit das 03:30.

## 8. Pasta de entrada do Paperless (Ficha 7)

Um arquivo posto na pasta de entrada vira documento do dono no Paperless e **some da pasta** quando entra. Arquivo
que continua lá não entrou (formato sem suporte, por exemplo); a conferência das 07:00 avisa depois de 24 h.
Cada pessoa tem a sua pasta, compartilhada só com os aparelhos dela. **Nunca compartilhe `/srv/paperless/consumir`
inteira**: ela tem a pasta da outra pessoa. Sem compartilhamento entre o Leonardo e a Nathalia (Ficha 6, decisão 3).

| Pasta (ID) | No i7 | Aparelhos |
|---|---|---|
| `paperless-leonardo` | `/srv/paperless/consumir/leonardo` | Mac, PC Windows e iPhone do Leonardo |
| `paperless-nathalia` | `/srv/paperless/consumir/nathalia` | os da Nathalia (quando ela entrar, PLANO 1b) |

**No i7** (GUI pelo túnel da seção 1), Adicionar pasta:

1. Rótulo `Paperless Leonardo`, ID `paperless-leonardo`, caminho `/srv/paperless/consumir/leonardo` (já existe).
2. Tipo **Enviar e receber**. Versionamento: nenhum (o Paperless guarda o original).
3. Aba Ignorar padrões: cole `paperless/deploy/syncthing/.stignore` antes de salvar.
4. Aba Compartilhamento: marque só os aparelhos do dono.
5. Em cada aparelho remoto (Editar), deixe desligados "Introdutor" e "Aceitar automaticamente". Aparelho novo entra
   só pelo ID, aqui.

O Syncthing roda como `<usuario>` (uid 1000), o mesmo uid do Paperless, que assim consegue apagar o arquivo que entrou.

**No Mac**: crie `~/Documents/Paperless-entrada` e aceite a pasta `paperless-leonardo` apontando para ela, tipo
**Enviar e receber**, versionamento **Lixeira** com 14 dias (guarda a cópia que some até o backup das 03:45), e cole o
`.stignore` antes de salvar. Se a pasta Documentos estiver no iCloud com "Otimizar armazenamento", o arquivo ainda não
baixado vira `.icloud` e não viaja: mande só arquivo que está no Mac.

**No PC Windows** (junto com o vault, PLANO 2.2): igual ao Mac, em `%USERPROFILE%\Documents\Paperless-entrada`, com
"Ignorar permissões" ligado (Avançado). O arquivo passa só pela rede privada até o i7.

**No iPhone (Synctrain, junto com o vault, PLANO 2.2)**: aceite a pasta `paperless-leonardo`; se o Synctrain oferecer versionamento, Lixeira com 14
dias. Para mandar: app Arquivos → Synctrain → pasta da entrada → ⋯ → "Escanear documentos", ou, de qualquer app,
Compartilhar → "Salvar em Arquivos" nessa pasta. Abra o Synctrain para ele enviar (o iOS limita o segundo plano).

**Conferir**: ponha um PDF na pasta do Mac. Em ~1 min ele some do Mac e do iPhone, e pelo app "me mostra o último
documento que entrou" traz o arquivo. O teste de isolamento está em `docs/IMPLANTACAO.md` P10.

## Se algo der errado

- Apareceu `.sync-conflict-*`: junte à mão e apague o arquivo de conflito.
- Syncthing "Desatualizado" por muito tempo: veja se o outro aparelho está ligado e na tailnet.
- Apagou nota por engano: recupere de `.stversions` (produção) ou do `git` (`git -C /srv/assistente/vault checkout -- <arquivo>`).
- Arquivo não some da pasta de entrada: o Paperless não aceitou. Veja `docker compose logs webserver` no projeto
  `paperless/` (ou o aviso em `journalctl -u paperless-conferir`) e tire o arquivo da pasta.
- Dois aparelhos comitaram: pare, não force push, e peça ajuda antes de mexer.
