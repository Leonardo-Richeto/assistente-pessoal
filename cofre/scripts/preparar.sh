#!/usr/bin/env bash
# Sobe o cofre (Ficha 11) com o cadastro fechado e confere. Idempotente: rode de novo depois de trocar a versão.
#
#   COFRE_HOME=/srv/cofre cofre/scripts/preparar.sh
#
# Para criar a conta: cofre/scripts/cadastro.sh abrir, crie a conta e cadastro.sh fechar.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,6p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac

descobrir_home
conferir_env
criar_pastas
log "subindo (primeira vez: baixa as imagens)"
SIGNUPS_ALLOWED=false subir
bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
log "pronto. Endereço: $(valor_env DOMINIO)"
