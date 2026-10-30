#!/usr/bin/env bash
# Teste do scripts/atualizar.sh sem Docker e sem sudo de verdade (os dois viram stubs que anotam a chamada).
#   bash scripts/testes/test_atualizar.sh
# Monta um "GitHub" falso (repo local mínimo) e duas instâncias clonadas numa pasta temporária.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
falhas=0
confere() { if eval "$2"; then echo "ok    $1"; else echo "FALHA $1"; falhas=$((falhas + 1)); fi; }

# Stubs: docker e sudo só anotam; sudo roda o comando sem privilégio.
mkdir -p "$T/bin"
printf '#!/bin/sh\necho "docker $*" >>"%s/chamadas"\n' "$T" >"$T/bin/docker"
printf '#!/bin/sh\necho "sudo $*" >>"%s/chamadas"\nexec env "$@"\n' "$T" >"$T/bin/sudo"
chmod +x "$T/bin/docker" "$T/bin/sudo"
export PATH="$T/bin:$PATH"

# "GitHub" falso: verificar.sh e preparar_host.sh que só anotam; verificar falha se existir FALHAR_<instância>.
git init -q "$T/origem"
mkdir -p "$T/origem/scripts" "$T/origem/deploy/systemd"
printf '#!/bin/sh\necho "verificar $ASSISTENTE_HOME" >>"%s/chamadas"\n[ ! -e "%s/FALHAR_$(basename "$ASSISTENTE_HOME")" ]\n' "$T" "$T" >"$T/origem/scripts/verificar.sh"
printf '#!/bin/sh\necho "preparar $ASSISTENTE_HOME" >>"%s/chamadas"\n' "$T" >"$T/origem/scripts/preparar_host.sh"
echo v1 >"$T/origem/deploy/systemd/x.timer"
git -C "$T/origem" add -A && git -C "$T/origem" -c user.name=t -c user.email=t@t commit -qm v1

for n in assistente assistente-nathalia; do
  mkdir -p "$T/srv/$n"
  git clone -q "$T/origem" "$T/srv/$n/app"
  touch "$T/srv/$n/.env"
done
mkdir -p "$T/srv/assistente-sem-env/app/.git"  # sem .env: fica de fora

rodar() { : >"$T/chamadas"; ATUALIZAR_BASE="$T/srv" bash "$REPO/scripts/atualizar.sh" "$@" >"$T/saida" 2>&1; }
commit_novo() {  # <arquivo> <conteúdo>
  mkdir -p "$(dirname "$T/origem/$1")"; echo "$2" >"$T/origem/$1"
  git -C "$T/origem" add -A && git -C "$T/origem" -c user.name=t -c user.email=t@t commit -qm "$2"
}

rodar
confere "primeira vez (sem .atualizado): sobe tudo, com preparar_host" \
  '[ "$(grep -c "^preparar" "$T/chamadas")" = 2 ] && [ -s "$T/srv/assistente/.atualizado" ]'
rodar
confere "sem commit novo, nada roda" '[ ! -s "$T/chamadas" ] && grep -q "nada a fazer" "$T/saida"'

commit_novo servidor/x.py v2
rodar
confere "commit novo: as duas sobem, a do Leonardo primeiro" \
  '[ "$(grep -c "^verificar" "$T/chamadas")" = 2 ] && head -n 1 "$T/chamadas" | grep -q "compose up -d --build" && sed -n 2p "$T/chamadas" | grep -q "srv/assistente$"'
confere "sem timer mudado, sem preparar_host" '! grep -q "^preparar" "$T/chamadas"'
confere "instância sem .env fica de fora" '! grep -q "sem-env" "$T/chamadas"'

commit_novo deploy/systemd/x.timer v3
rodar
confere "timer mudado: preparar_host com sudo nas duas" '[ "$(grep -c "^preparar" "$T/chamadas")" = 2 ] && grep -q "^sudo ASSISTENTE_HOME=" "$T/chamadas"'

commit_novo servidor/x.py v4
touch "$T/FALHAR_assistente"
rodar
confere "verificar falha na do Leonardo: para e não mexe na da Nathalia" \
  '! grep -q nathalia "$T/chamadas" && [ "$(git -C "$T/srv/assistente-nathalia/app" log -1 --format=%s)" = v3 ]'
rm "$T/FALHAR_assistente"
rodar
confere "rodar de novo refaz a do Leonardo (não passou) e sobe a da Nathalia" \
  '[ "$(grep -c "^verificar" "$T/chamadas")" = 2 ] && grep -q "nathalia" "$T/chamadas"'
rodar
confere "depois de passar, nada roda" '[ ! -s "$T/chamadas" ]'

commit_novo servidor/x.py v5
rodar --so assistente-nathalia
confere "--so sobe só a escolhida" '[ "$(grep -c "^verificar" "$T/chamadas")" = 1 ] && grep -q "^verificar .*nathalia" "$T/chamadas"'

commit_novo paperless/y.yml v6
rodar --so assistente
confere "mudança no paperless/ só avisa" 'grep -q "paperless/ ou cofre/ mudaram" "$T/saida"'

[ "$falhas" -eq 0 ] && echo "test_atualizar: ok" || { echo "test_atualizar: $falhas falha(s)"; cat "$T/saida"; exit 1; }
