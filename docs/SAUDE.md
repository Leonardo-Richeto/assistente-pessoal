# Saúde do Apple Watch: pasta de entrada (Ficha 14)

O histórico do app Saúde entra pelo `export.zip`. Você exporta no iPhone, manda por AirDrop para a pasta
`Saude-entrada` do Mac, e o Syncthing a leva ao i7. Lá, o serviço `saude` importa cada `.zip` parado há 2 min (ele
olha a cada 5 min) e o tira da pasta. Reimportar não duplica: exporte quando quiser, o histórico inteiro de novo.
O envio diário pelo Atalho do iOS espera o Tailscale no iPhone (Ficha 14, calibração, item 5).

Dado de saúde fica só no banco de casa e no backup cifrado. Nunca no vault, no GitHub nem no repositório. Só a
instância do Leonardo tem o perfil `saude`.

| Pasta (ID) | No i7 | No Mac |
|---|---|---|
| `saude-leonardo` | `/srv/assistente/data/saude/entrada` | `~/Documents/Saude-entrada` |

O último `.zip` importado fica em `/srv/assistente/data/saude/importados`, fora da pasta sincronizada. Ele guarda o
que não vira linha no banco, como o `export_cda.xml`.

## 1. No i7, uma vez

1. No `/srv/assistente/.env`, acrescente `saude` ao `COMPOSE_PROFILES` (ex.: `tailscale,pluggy,saude`).
2. `bash scripts/atualizar.sh`. Como o `preparar_host.sh` mudou, ele o roda (pede a senha do sudo) e cria as
   pastas de `data/saude` com dono uid 1000, o mesmo do Syncthing e do container. Depois roda a migração 0008 e
   sobe o serviço `saude`.
3. Confira: `docker compose --env-file ../.env logs saude | tail -3` mostra "vigiando /entrada a cada 5 min".

## 2. A pasta no Syncthing

**No i7** (GUI pelo túnel da seção 1 de `docs/SYNCTHING.md`), Adicionar pasta:

1. Rótulo `Saude Leonardo`, ID `saude-leonardo`, caminho `/srv/assistente/data/saude/entrada`.
2. Tipo **Enviar e receber**. Versionamento: nenhum (o i7 guarda o último importado).
3. Aba Ignorar padrões: `(?d).DS_Store`.
4. Aba Compartilhamento: só o Mac.

**No Mac:** crie `~/Documents/Saude-entrada` e aceite a pasta `saude-leonardo` apontando para ela, tipo **Enviar e
receber**, versionamento **nenhum**. Se a pasta Documentos estiver no iCloud com "Otimizar armazenamento", mande só
arquivo que está no Mac (o `.icloud` não viaja).

## 3. Exportar e mandar

1. No iPhone, abra o app Saúde, toque na sua foto e em **Exportar Todos os Dados de Saúde**. Leva alguns minutos.
2. Compartilhe com AirDrop para o Mac e salve em `~/Documents/Saude-entrada`.
3. Em até 10 min o arquivo some da pasta do Mac. Ele foi importado.

Confira no i7:

```bash
docker compose --env-file ../.env logs saude | tail -5
```

O esperado é "exportar.zip importado (saude_amostras: N novos, ...)". Na primeira vez, o histórico inteiro leva
alguns minutos.

## Se algo der errado

- O arquivo não some da pasta: veja o log acima.
  - "recusado" diz o motivo. O arquivo fica até você trocá-lo, e só é tentado de novo quando mudar.
  - "não entrou ... tento de novo" é falha do banco (por exemplo, durante o `atualizar.sh`). Ele tenta de novo
    sozinho, com espera que dobra até 6 h.
  - "importado, mas não consegui movê-lo": os dados já estão no banco. Tire o arquivo da pasta à mão; ele não é
    importado de novo.
- Cada tentativa fica em `saude_importacoes` (ok, contagens e erro, sem valor de saúde).
- Para importar à mão um arquivo no i7:
  `docker compose --env-file ../.env run --rm -v <pasta do zip>:/z:ro saude python -m assistente.saude importar /z/<arquivo>.zip`.
