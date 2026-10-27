#!/usr/bin/env bash
# Abre ou fecha o cadastro de conta do cofre (Ficha 11, regra 3). Só para criar a conta; feche logo depois.
#
#   COFRE_HOME=/srv/cofre cofre/scripts/cadastro.sh abrir
#   COFRE_HOME=/srv/cofre cofre/scripts/cadastro.sh fechar
#
# O .env não muda: o valor fica no container recriado agora, inclusive depois de um reboot (o Docker reinicia o
# mesmo container). Só o `fechar` ou o preparar.sh voltam ao fechado. A conferência diária acusa o aberto.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in
  abrir) VALOR=true ;;
  fechar) VALOR=false ;;
  -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
  *) falha "use: cadastro.sh abrir|fechar" ;;
esac
descobrir_home
conferir_env
SIGNUPS_ALLOWED="$VALOR" subir
[ "$(env_no_container SIGNUPS_ALLOWED)" = "$VALOR" ] || falha "o container não ficou com SIGNUPS_ALLOWED=$VALOR."
if [ "$VALOR" = true ]; then
  aviso "cadastro ABERTO. Crie a conta em $(valor_env DOMINIO) e feche já: cofre/scripts/cadastro.sh fechar"
else
  bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
  log "cadastro fechado."
fi
