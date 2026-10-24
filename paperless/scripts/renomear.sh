#!/usr/bin/env bash
# Troca o nome de uma pessoa no Paperless único: usuário, workflow da pasta e a pasta de consumo. Os documentos,
# o token e as permissões ficam com o mesmo usuário. Idempotente. Antes, troque o nome em USUARIOS no .env.
#
#   PAPERLESS_HOME=/srv/paperless paperless/scripts/renomear.sh <de> <para>
#
# 1. confere os nomes, o .env (PARA em USUARIOS, DE fora), o webserver de pé e consumir/<de> sem arquivo
#    (arquivo esperando entrar mudaria de pasta no meio da troca; espere o Paperless consumir);
# 2. renomeia o usuário e o workflow "dono: consumir/<de>", nome e caminho juntos (paperless/deploy/gestao.py);
# 3. move consumir/<de> (vazia) para consumir/<para>, se esta ainda não existe;
# 4. roda o preparar.sh, que acerta o resto e confere a Ficha 6.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help|"") sed -n '2,11p' "$0"; exit 0 ;; esac
[ "$#" -eq 2 ] || falha "uso: renomear.sh <de> <para>"
DE="$1" PARA="$2"
for nome in "$DE" "$PARA"; do
  [[ "$nome" =~ ^[a-z][a-z0-9_]{0,29}$ ]] || falha "nome inválido: '$nome' (minúsculas, dígitos e _)."
done
[ "$DE" != "$PARA" ] || falha "de e para são iguais."

descobrir_home
conferir_env
[[ " $(valor_env USUARIOS) " == *" $PARA "* ]] || falha "ponha '$PARA' em USUARIOS no $ENV_FILE antes."
[[ " $(valor_env USUARIOS) " != *" $DE "* ]] || falha "tire '$DE' de USUARIOS no $ENV_FILE antes."
[ -n "$(dc ps -q webserver 2>/dev/null | tr -d '\r')" ] || falha "o webserver está parado (rode preparar.sh antes)."
ORIGEM="$HOME_DIR/consumir/$DE" DESTINO="$HOME_DIR/consumir/$PARA"
if [ -d "$ORIGEM" ] && [ -n "$(find "$ORIGEM" -mindepth 1 -not -path "$ORIGEM/.stfolder*" -print -quit)" ]; then
  falha "consumir/$DE tem arquivo esperando entrar; espere o Paperless consumir (ou tire os arquivos) e rode de novo."
fi

gestao renomear DE="$DE" PARA="$PARA" | sed "s/^/$NOME_SCRIPT: /"
[ "${PIPESTATUS[0]}" -eq 0 ] || falha "a troca do usuário falhou."

if [ -d "$ORIGEM" ]; then
  if [ -d "$DESTINO" ]; then
    log "consumir/$PARA já existe; consumir/$DE ficou vazia e sem uso (nada é apagado)."
  else
    mv "$ORIGEM" "$DESTINO" || falha "não consegui mover $ORIGEM."
    log "pasta: consumir/$DE -> consumir/$PARA"
  fi
fi

bash "$(dirname "$0")/preparar.sh" || falha "o preparar.sh falhou (veja acima)."
log "pronto: $DE agora é $PARA."
