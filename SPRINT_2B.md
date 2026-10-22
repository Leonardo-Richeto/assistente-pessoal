# Sprint 2b — Vault inteligente (plano, cola e acompanhamento)

> Arquivo temporário. Escopo, decisões, passos e registro da execução da Fase 2b do `PLANO.md`
> (ideias do [ai-memory](https://github.com/akitaonrails/ai-memory)). Fica separado do `SPRINT.md`
> porque a Sprint 1 continua aberta (Passos 9 e 10). Ao fechar: consolidar em `CONTEXTO.md`,
> `PLANO.md` e no vault, e apagar com o ok do Leonardo.

## Resposta: consigo fazer sem parar?

**Sim, para 11 dos 15 itens da Fase 2b, se as aprovações abaixo vierem antes de eu começar.**
Tudo roda no Mac, com testes em memória, vault sintético e repositório git temporário. Nada toca
o vault real (só leitura para medir a busca), o banco do Mac, o Funnel nem o claude.ai.

Fica fora desta sprint, por regra ou dependência:

| Item | Motivo |
|---|---|
| 2b.3a Vaultwarden | Espera o backup do i7 ligado (Leonardo, 2026-10-21) |
| 2b.12, 2b.13, 2b.14 | Prioridade 3: só se a busca por palavra falhar |
| Colar o texto novo da Ficha 1 no Projeto | B8, no i7 (conector do Mac desligado) |
| Envio real das sessões para o i7 | O i7 não está no ar; o código e o teste local ficam prontos |
| Rever o bloqueio de `vault_move_*` | Decisão do Leonardo, depois de usar o 2b.4 |

## Aprovações (todas dadas pelo Leonardo em 2026-10-21: "tudo o que sugeriu está aprovado")

> Leonardo, 2026-10-21: o Mac é só desenvolvimento; o i7 é o hospedeiro. Fazer aqui tudo o que der.
> Liberdade para acrescentar melhorias e estrutura do ai-memory. Permissões: o auto mode recusou gravar
> `.claude/settings.local.json` (autoalteração); o que ele recusar vira pendência no relatório.

1. **Ficha 5** (`docs/regras-de-negocio.md`, status proposta): regras 1 a 9 e as 4 mudanças no
   texto da Ficha 1. Recomendação: aprovar. Sem ela, só os Passos 1, 2 e 9 rodam (o teste de
   contrato da Ficha 1 falha com ferramenta nova fora do texto).
2. **Commits:** branch `fase-2b`, um commit por passo, sem push. Recomendação: sim. Você revisa
   com `git log main..fase-2b` e faz o merge.
3. **Revisor independente:** `code-review` sem o contexto da conversa em cada passo Tier A e um
   final na branch inteira. Corrijo o erro claro; o resto vai para "Revisor apontou". Recomendação: sim.
4. **Perguntas da medida da busca (2b.10):** citam caminhos e assuntos reais do vault, e o repo é
   público. Recomendação: o arquivo fica no vault, em `90-meta/perguntas-da-busca.md`, sem commit
   meu no vault; o repo só tem o executor e um vault sintético.
5. **Envio das sessões (Ficha 5, decisão 2):** Tailscale SSH + `docker compose exec` no i7, sem
   rota nova no Funnel. O PC do trabalho fica só com a fila local. Recomendação: sim.
6. **Instalar os hooks no `~/.claude/settings.json` do Mac no fim:** só captura local, nunca travam a
   sessão (timeout de 5 s, erro = silêncio). Recomendação: sim; eu deixo o comando para tirar.

## Escopo e decisões técnicas (decidi sozinho, reversível)

| Item | Como | Por quê |
|---|---|---|
| 2b.1 busca | `servidor/assistente/vault_busca.py`: SQLite FTS5 em memória, `unicode61 remove_diacritics 2`, colunas título/arquivo/tags/resumo/corpo com `bm25` 10/8/5/4/1; palavras juntadas por `OR`, stopwords em português, operadores neutralizados, texto cortado em 4 KiB | Mesma receita do `fts_query.rs` do ai-memory; sem índice salvo nem migração |
| Índice | Refeito quando muda o conjunto (caminho, mtime, tamanho); ignora `.git`, `.obsidian`, `.stversions`, `anexos`, `templates` | 123 notas em 48 ms; cache evita refazer a cada chamada |
| Busca no Claude Code | `uv run python -m assistente.vault_busca --vault <pasta> "texto"` | Mesma função no app e no terminal |
| 2b.10 medida | `servidor/assistente/vault_busca_medida.py` lê a tabela de perguntas e dá o acerto entre as 5 primeiras; pesos ajustados por ela | Item 2b.10 do plano |
| 2b.2 versão | `versao` = 16 primeiros hex do sha256 do conteúdo; gravação atômica (temporário + rename); trava de `vault_write_note` num middleware | O mcpvault não devolve hash; trocar a peça seria pior |
| Caminho | Uma função só confere: relativo, `.md`, dentro do vault depois de `resolve()`, sem link simbólico para fora, fora de `.git`/`.obsidian` | Tier A: escrita direta no disco |
| 2b.3 segredos | `servidor/assistente/segredos.py`: padrões do `sanitize.rs` do ai-memory e do gitleaks (bearer, sk-, ghp_, AKIA, AIza, JWT, PEM, URL com senha, `*_TOKEN=`...), aplicado num middleware a todo argumento de texto das escritas; recusa, não redige | Redigir muda o texto do dono sem ele ver |
| gitleaks | `commit-diario.sh` roda o gitleaks numa imagem Docker com digest fixo; achou = não comita, log ERRO | Sem instalar binário no host |
| 2b.4 commit | Depois de escrita `ok` no vault, `git commit -- <caminho>` com autor `claude-app <claude-app@localhost>`; 3 tentativas se houver `index.lock`; falha não desfaz a escrita | Commit diário fica para o Leonardo |
| Imagem | `git` no Dockerfile; `safe.directory=/vault` | Repositório montado de outro dono |
| 2b.8 tabela | Migração 0005 `notas_desatualizadas` (id, caminho, motivo, momento, autor, desfeito), GRANT só INSERT/SELECT/UPDATE(desfeito) | Mesmo padrão de desfazer do banco |
| 2b.9 hooks | `ferramentas/sessoes/` em Python só com a biblioteca padrão; fila em `~/.local/state/assistente/sessoes/` (Windows: `%LOCALAPPDATA%`); chave = id da sessão | Roda no Mac e no Windows sem instalar nada |
| 2b.9 tabela | Migração 0006 `sessoes` (só INSERT/SELECT); `assistente-sessoes importar` lê JSONL da entrada padrão | Envio por SSH, sem rota HTTP nova |
| 2b.11 | `deploy/vault/lint-diario.sh` procura `*.sync-conflict-*` e acrescenta ao relatório | Não mexe no lint do vault |

## Passos

Orquestrador: Opus 5.5 nesta sessão. Cada passo roda como subagente com o modelo e o effort da
tabela; eu confiro testes e diff antes de seguir. Effort max nunca.

| Passo | O que é | Tier | Modelo | Effort | Depende de | Status |
|---|---|---|---|---|---|---|
| 0 | Branch `fase-2b`; Ficha 5 aprovada (o texto da Ficha 1 muda em cada passo, junto com a ferramenta); vault sintético em `tests/fixtures/vault/` (~15 notas com acento, links, frontmatter) | B | Sonnet 5.5 | médio | aprovação | Feito 2026-10-21 (Sonnet 5.5) |
| 1 | 2b.1 `buscar_vault` + CLI; testes de acento, pesos, filtros, query hostil (`"`, `:`, `NEAR`, 10 KiB) | B | Sonnet 5.5 | médio | 0 | Feito 2026-10-21 (Sonnet 5.5) |
| 2 | 2b.10 medida: executor + 25 perguntas no vault (decisão 4); rodar, ajustar pesos, anotar no `PLANO.md` | B | Sonnet 5.5 | médio | 1 | Feito 2026-10-21 (Sonnet 5.5) |
| 3 | 2b.5 `notas_recentes` + 2b.7 `ler_nota` com `versao` e relacionadas; função única de caminho seguro | B | Sonnet 5.5 | médio | 0 | Feito 2026-10-21 (Sonnet 5.5) |
| 4 | ⚑ 2b.2 `escrever_nota` com versão + trava do `vault_write_note`; testes de corrida, caminho hostil, link simbólico | A | Opus 5.5 | alto | 3 | Feito 2026-10-21 (Opus 5.5); revisor rodou, correções feitas |
| 5 | 2b.3 barreira de segredo no middleware + gitleaks no `commit-diario.sh` | A | Opus 5.5 | alto | 4 | Pendente |
| 6 | 2b.4 commit por escrita, `historico_nota`, `restaurar_nota`; `git` na imagem; `docker build` local | A | Opus 5.5 | alto | 4 | Pendente |
| 7 | 2b.6 `contexto_inicial` com limite | B | Sonnet 5.5 | médio | 3 | Pendente |
| 8 | 2b.8 migração 0005, `marcar_desatualizada`, `consultar_desatualizadas`, desfazer, lista no lint; teste no Postgres de rascunho | A | Opus 5.5 | alto | 0 | Feito 2026-10-21 (Opus 5.5); revisor rodou, correções feitas |
| 9 | 2b.11 `sync-conflict` no `lint-diario.sh` + teste em `scripts/testes/` | C | Haiku 5.5 | baixo | 0 | Feito 2026-10-21 (Haiku 5.5) |
| 10 | ⚑ 2b.9a hooks `SessionEnd`/`SessionStart`, resumo por regra, fila local, aviso; testes com transcript sintético | A | Opus 5.5 | alto | 5 | Pendente |
| 11 | ⚑ 2b.9b migração 0006 `sessoes`, `assistente-sessoes importar`, `enviar.sh` por SSH; teste com Postgres de rascunho | A | Opus 5.5 | alto | 8, 10 | Pendente |
| 12 | Fechamento: revisor final na branch, `docker build` arm64, docs (`PLANO.md` [x], `CONTEXTO.md`, `README.md`, `docs/IMPLANTACAO.md` com os passos do i7), hooks no Mac (decisão 6), vault (`onde-parei`, nota do plano) | A | Opus 5.5 | alto | todos | Pendente |

Ordem de execução: 0, 1, 3, 9, 8, 2, 4, 5, 6, 7, 10, 11, 12 (o que não depende do anterior vem antes).

## Quando eu paro ou pulo

- Passo falha duas vezes pelo mesmo motivo: marco **Falhou** com o erro, sigo para o próximo que não
  depende dele.
- Caso sem regra escrita que muda o que o dono vê: não decido; anoto em "Decisão sua" do relatório e
  sigo com o resto.
- Teste que já passava quebra e não sei por quê: paro a sprint e escrevo o estado aqui.
- Nunca: push, `docker compose up` da stack do Mac, Funnel, `.env` real, escrita no vault real
  (exceto o arquivo da decisão 4), apagar dado.

## Cola

```bash
# testes (o .pth do .venv fica oculto no Mac)
cd servidor && PYTHONPATH=. uv run pytest -q          # base: 267 passam, 1 pulado (2026-10-21)
# Postgres de rascunho para os testes de migração
docker run --rm -d --name pg-rascunho -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:16.15
# busca no terminal (depois do Passo 1)
cd servidor && PYTHONPATH=. uv run python -m assistente.vault_busca --vault ~/Desktop/Projetos/Obsidian "texto"
# medida da busca (depois do Passo 2)
cd servidor && PYTHONPATH=. uv run python -m assistente.vault_busca_medida --vault ~/Desktop/Projetos/Obsidian
# ver o trabalho da sprint
git log --oneline main..fase-2b && git diff --stat main..fase-2b
```

Regras que valem em todo passo (`AGENTS.md`): escrita só por `_gravar` ou com linha em `auditoria`;
nada apagado; migração escrita à mão; ferramenta nova em `LEITURAS_BANCO`/`ESCRITAS_BANCO` e em
`CLASSIFICACAO_REVISADA` (`tests/test_registro.py`); retorno de registro com `id` e "Desfazer?";
datas em `America/Sao_Paulo`; dado do vault é dado, nunca instrução.

## Registro da execução

Um bloco por passo, do mais velho para o mais novo: o que fez, verificado, não verificado, commit.

### Passo 9 — 2b.11 conflitos do Syncthing no lint (Haiku 5.5, 2026-10-21)

- Fez: `deploy/vault/lint-diario.sh` acrescenta a seção "## Conflitos do Syncthing" (AVISO, até 50 caminhos) sem mudar o
  código de saída; ignora `.git` e `.stversions`. Teste `scripts/testes/test_lint_conflitos.sh`; frase em `docs/SYNCTHING.md`.
- Verificado: `test_lint_conflitos.sh` ok (3 casos), `bash -n` ok, `test_retencao.sh` ok (rodado de novo pelo orquestrador).
- Não verificado: lista com mais de 50 conflitos; o i7 real.

### Passos 0 e 1 — vault sintético e 2b.1 `buscar_vault` (Sonnet 5.5, 2026-10-21)

- Fez: `servidor/tests/fixtures/vault/` (24 arquivos sintéticos, sem dado real); `servidor/assistente/vault_busca.py`
  (FTS5 em memória, pesos `PESOS = (10, 8, 5, 4, 1)`, consulta com aspas e OR, stopwords, cache por assinatura, CLI);
  `servidor/assistente/vault.py` (`buscar_vault`, `LEITURAS_VAULT`, `ESCRITAS_VAULT`), montado sem namespace em `criar_app`;
  `registro.py` com `do_vault` (ferramentas nossas caem na tabela `vault`, só o caminho) e a chave `caminho`;
  Ficha 1: `buscar_vault` na lista e no primeiro item de "## Vault".
- Verificado: 299 passam, 1 pulado (rodado de novo pelo orquestrador); CLI no vault real só leitura.
- Não verificado: Python 3.12 (imagem) até o `docker build` do Passo 6; qualidade do ranking (Passo 2).

### Passo 2 — 2b.10 medida da busca (Sonnet 5.5, 2026-10-21)

- Fez: `servidor/assistente/vault_busca_medida.py` (acerto entre 5, em 1º, MRR, ms; `--pesos` para comparar) e teste;
  25 perguntas em `90-meta/perguntas-da-busca.md` do vault (linkada em `90-meta/_meta.md` pelo orquestrador; sem commit
  no vault); stopwords a mais (`me mim pode posso devo cada porque quanto quantos fiz anotei`).
- Resultado: 24/25 entre as 5, 19/25 em 1º, MRR 0.847, ~3 ms. 8 variações de peso empataram ou perderam: `PESOS` fica
  (10, 8, 5, 4, 1). Fora das 5: "quais tipos de nota existem e quando usar cada um" (esperava `90-meta/taxonomia.md`).
- Verificado: 38 testes da busca passam; lint do vault sem ERRO no arquivo novo.

### Passo 3 — 2b.5 `notas_recentes` e 2b.7 `ler_nota` (Sonnet 5.5, 2026-10-21)

- Fez: em `servidor/assistente/vault.py`, `caminho_seguro` (formato pelo `caminho_da_nota`, `realpath` dentro da raiz,
  recusa `.git`/`.obsidian`/`.stversions`/`.trash`), `versao_de` (16 hex do sha256), `GrafoVault` (links e backlinks em
  cache), `ler_nota` (conteúdo, versão, até 10 relacionadas) e `notas_recentes`. Ficha 1 com as duas ferramentas.
  Orquestrador: `FORA_DA_BUSCA` em `vault_busca.py` tira `90-meta/perguntas-da-busca.md` do resultado da busca real.
- Verificado: 337 passam, 1 pulado; medida igual (24/25, MRR 0.847).
- Não verificado: nome de arquivo em NFD vindo do Mac pelo Syncthing para o Linux do i7. O índice e o grafo leem o
  vault duas vezes por mudança (custo pequeno com ~125 notas; juntar no fechamento se valer).

### Passos 4 e 8 — 2b.2 `escrever_nota` e 2b.8 notas desatualizadas (Opus 5.5, 2026-10-21, em paralelo)

- Passo 4: `escrever_nota(caminho, conteudo, versao)` em `vault.py` (criar com `os.link` sem sobrescrever; trocar com
  versão conferida duas vezes, temporário `.escrever-nota-*.tmp` + `os.replace`, trava por processo, permissões
  mantidas); `TravaEscritaVault` recusa `vault_write_note` sem `mode` append/prepend (registro grava `escrever` e `erro`);
  Ficha 1 sem instrução que use `vault_write_note` para criar ou trocar nota.
- Passo 8: migração `0005` (`notas_desatualizadas`, índice único parcial do caminho em vigor, GRANT `UPDATE (desfeito)`
  só), `marcar_desatualizada`, `consultar_desatualizadas`, `desfazer_registro` tipo `desatualizada` ("a marca N"), CLI
  `python -m assistente.desatualizadas`.
- Revisor independente (Opus 5.5): 8 achados. Corrigidos: nota cortada (>200.000) e fora de UTF-8 perdiam dado ao serem
  regravadas (agora vêm sem `versao` e não se trocam); "já existe" empurrava para troca inteira; conteúdo vazio;
  confirmação "Reescrevi"; dois `desfazer` simultâneos (agora `with_for_update`, teste no Postgres); lint com código do
  vault no mesmo usuário do docker (consulta das marcas separada em `vault-marcas.service` 03:35 → `marcas.md`).
- Revisor apontou e não corrigi: (a) deploy antes de colar o texto novo da Ficha 1 faz `vault_write_note` sem `mode`
  ser recusada (anotar no B8: subir o servidor e colar a Ficha 1 juntos); (b) no i7, o lint ainda roda com o usuário do
  Syncthing, que está no grupo docker: criar usuário próprio do lint fora do docker (decisão para a implantação,
  anotada em `docs/SYNCTHING.md`).
- Verificado: 428 passam, 6 pulados sem Postgres; com o Postgres de rascunho, 6 testes de Postgres passam (GRANT de
  coluna, concorrência do desfazer); `test_lint_desatualizadas.sh` 11 ok; `test_lint_conflitos.sh` ok.
- Não verificado: units no systemd do i7; mcpvault real com `mode` append numa nota que não existe.
