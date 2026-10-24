# Notas técnicas

Fatos que pegam quem mexe no código e que não cabem no `README.md`. Vieram dos "Avisos vivos" das Sprints 1 e 2b
(fechadas em 2026-10-24; o histórico completo está no git, nos arquivos `SPRINT*.md` apagados).

## Ambiente
- **Mac:** `uv run pytest` falha com `No module named 'assistente'`. O `.pth` editável do `.venv` ganha a flag
  `hidden` do macOS e o Python 3.14 o ignora. Rode `PYTHONPATH=. uv run pytest` ou `chflags nohidden .venv/lib/python3.14/site-packages/*.pth`. No Linux não acontece.
- O `uv` local usa Python 3.14; a imagem usa 3.12. Se o resultado depender da versão, rode dentro do container.
- Vault de teste nunca aponta para o vault real do Leonardo.

## Registro de chamadas (`servidor/assistente/registro.py`)
- Só é leitura o que está em `LEITURAS_PECAS` (`servidor.py`) ou `LEITURAS_BANCO` (`banco.py`). O resto conta como escrita:
  grava a linha `escrever` na `auditoria` antes da chamada e o resultado depois. Se a `escrever` não grava, a chamada é recusada.
- Ferramenta nova do banco: `LEITURAS_BANCO` ou `ESCRITAS_BANCO` e também `CLASSIFICACAO_REVISADA` (`tests/test_registro.py`), decidindo à mão se lê ou escreve.
- Ferramenta nova de peça: `PERMITIDAS` (ou `BLOQUEADAS`) e `LEITURAS_PECAS`/`ESCRITAS_PECAS`.
- `tests/test_contrato_ficha1.py` lê o texto do Projeto em `docs/regras-de-negocio.md`: ferramenta nova exige linha na Ficha 1.
- A tabela `chamadas` só aceita INSERT e SELECT. Tabela nova: conceda os GRANTs explicitamente na migração.
- `dados` guarda só caminho de nota e ids inteiros do Paperless. Nunca texto.

## Vínculo com nota (`nota_vault`)
- `vincular_nota(tipo, id, caminho)` grava `vincular` na `auditoria`. `desfazer_registro(tipo="vinculo", id=N)` volta à nota anterior;
  o registro continua valendo. Só o vínculo mais novo do registro pode ser desfeito (pilha).
- O servidor confere só o formato do caminho, nunca abre o vault.
- O downgrade da migração 0004 é recusado se algum registro tem `nota_vault`.

## Login e limites
- `/register` 10/h e `/authorize` 30/h por IP; `/consent` usa o limite do `/authorize`; `/token` e `/auth/callback` 60/h. Teto global: `/register` 100/h, `/authorize` e `/consent` 300/h (D12). Reiniciar o servidor zera a contagem.
- O IP real vem do `X-Forwarded-For`, valendo só quando a conexão vem do loopback ou do gateway da rede Docker.
- Conta fora da lista não recebe token (`invalid_grant`, 401).
- O compose não repassa `AUTH_DESATIVADA`; o servidor recusa subir sem login com `PUBLIC_BASE_URL` não local e `JWT_SIGNING_KEY` com menos de 32 caracteres.
- O volume `oauth` guarda clientes e tokens cifrados com a `JWT_SIGNING_KEY`. Trocar a chave ou `down -v` obriga o conector a reconectar.
- Peça pronta em versão nova: regenere a fixture; o teste falha até cada nome novo entrar em `PERMITIDAS` ou `BLOQUEADAS`.
