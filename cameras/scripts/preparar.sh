#!/usr/bin/env bash
# Sobe o Frigate da câmera (Ficha 18) e confere. Idempotente: rode de novo depois de mudar o config.yml ou a versão.
#
#   CAMERAS_HOME=/srv/cameras cameras/scripts/preparar.sh
#
# Primeira vez: o Frigate cria o usuário admin e mostra a senha no log; o script repete a linha. Troque a senha na
# tela (Configurações → Usuários) e guarde no cofre.
source "$(dirname "$0")/comum.sh"

case "${1:-}" in -h|--help) sed -n '2,7p' "$0"; exit 0 ;; "") ;; *) falha "opção desconhecida: $1" ;; esac

descobrir_home
conferir_env
criar_pastas
primeira=0; [ -e "$HOME_DIR/config/frigate.db" ] || primeira=1
# O repositório é a fonte do config.yml (Ficha 18).
install -m 600 "$CAMERAS_APP/deploy/config.yml" "$HOME_DIR/config/config.yml" || falha "não consegui copiar o config.yml."
log "subindo o Frigate (primeira vez: baixa ~1,5 GB de imagem)"
dc_quieto up -d --force-recreate frigate || falha "docker compose up falhou."
esperar_saudavel frigate 300 || falha "o Frigate não ficou saudável (docker compose logs frigate)."

if [ "$primeira" -eq 1 ]; then
  senha="$(dc logs frigate 2>/dev/null | grep -oE '(User|Password): [^ *]+' | tail -n 2 | tr '\n' ' ')"
  log "primeira subida. Login: ${senha:-procure 'Password' em: docker compose -p $(valor_env COMPOSE_PROJECT_NAME) logs frigate}"
fi

# A primeira gravação chega ao disco em ~1 min.
log "esperando a primeira gravação (até 3 min)"
for _ in $(seq 1 36); do
  m="$(minutos_ultima_gravacao)"; [ -n "$m" ] && [ "$m" -le 2 ] && break
  sleep 5
done
bash "$(dirname "$0")/conferir.sh" || falha "a conferência achou problema (veja acima)."
log "pronto.$(com_lan && echo " Painel: https://$(valor_env ENDERECO_LAN):$(valor_env PORTA_LAN) (certificado próprio: aceite o aviso uma vez)")"
