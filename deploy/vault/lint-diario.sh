#!/usr/bin/env bash
# Lint diário do vault: roda o 90-meta/lint-do-vault.py do próprio vault e guarda o relatório.
# Só lê o vault; não muda nota nenhuma. Sai com o código do lint (1 = há ERRO), para o
# systemd marcar o serviço como falho e aparecer em `systemctl --failed`.
# Chamado pelo vault-lint.service; também roda à mão:
#   VAULT_PATH=/srv/assistente/vault LINT_DIR=/srv/assistente/logs/vault-lint bash deploy/vault/lint-diario.sh
# O relatório fica FORA do vault, para não virar nota nem entrar no commit diário.
# Arquivo de conflito do Syncthing (*.sync-conflict-*) vira seção de AVISO no relatório; não muda o código.
# As notas marcadas como desatualizadas no banco viram seção de AVISO, lidas de $LINT_DIR/marcas.md, que o
# vault-marcas.service (marcas-desatualizadas.sh, 03:35) grava. O lint não chama docker: o código dele vem do
# vault, e o usuário dele não deve estar no grupo docker.
set -u

VAULT_PATH="${VAULT_PATH:-/srv/assistente/vault}"
LINT_DIR="${LINT_DIR:-/srv/assistente/logs/vault-lint}"
LINT="$VAULT_PATH/90-meta/lint-do-vault.py"

log() { echo "vault-lint: $*"; }

command -v python3 >/dev/null || { log "ERRO: python3 não instalado (sudo apt-get install -y python3)."; exit 2; }
[ -f "$LINT" ] || { log "ERRO: $LINT não existe (o vault está em $VAULT_PATH?)."; exit 2; }
mkdir -p "$LINT_DIR" || { log "ERRO: não consegui criar $LINT_DIR."; exit 2; }

# -I: o Python não carrega módulo da pasta do vault, que recebe arquivo de vários aparelhos.
python3 -I "$LINT" --vault "$VAULT_PATH" >"$LINT_DIR/ultimo.md.parcial"
CODIGO=$?
if [ "$CODIGO" -gt 1 ]; then
  rm -f "$LINT_DIR/ultimo.md.parcial"
  log "ERRO: o lint quebrou (código $CODIGO); o relatório anterior ficou."
  exit "$CODIGO"
fi

# Conflitos do Syncthing: aviso, não erro. Sem conflito, o relatório não muda.
CONFLITOS="$(find "$VAULT_PATH" -name '*.sync-conflict-*' -not -path '*/.git/*' -not -path '*/.stversions/*' | sort)"
if [ -n "$CONFLITOS" ]; then
  N="$(printf '%s\n' "$CONFLITOS" | grep -c .)"
  {
    echo ""
    echo "## Conflitos do Syncthing"
    echo ""
    echo "AVISO: $N arquivo(s) de conflito. Compare com a nota original, junte à mão e apague a cópia."
    printf '%s\n' "$CONFLITOS" | head -n 50 | while IFS= read -r f; do echo "- ${f#"$VAULT_PATH"/}"; done
    [ "$N" -gt 50 ] && echo "- ... e mais $((N - 50))"
  } >>"$LINT_DIR/ultimo.md.parcial"
fi

# Notas marcadas como desatualizadas (marcar_desatualizada, tabela do banco): aviso, não erro.
# Sem marcas.md (vault-marcas.service não instalado), pula em silêncio. Com mais de 24 h, só avisa.
MARCAS="$LINT_DIR/marcas.md"
if [ -f "$MARCAS" ]; then
  if [ -z "$(find "$MARCAS" -mmin -1440 2>/dev/null)" ]; then
    { echo ""; echo "AVISO: lista de marcas com mais de 24 h."; } >>"$LINT_DIR/ultimo.md.parcial"
  elif head -n 1 "$MARCAS" | grep -q '^AVISO:'; then  # a consulta falhou: a linha do aviso, sem seção
    { echo ""; head -n 1 "$MARCAS"; } >>"$LINT_DIR/ultimo.md.parcial"
  elif grep -q . "$MARCAS"; then
    {
      echo ""
      echo "## Notas marcadas como desatualizadas"
      echo ""
      echo "AVISO: revise cada nota e, se corrigiu, desfaça a marca no app."
      cat "$MARCAS"
    } >>"$LINT_DIR/ultimo.md.parcial"
  fi
fi
mv "$LINT_DIR/ultimo.md.parcial" "$LINT_DIR/ultimo.md"
log "$(sed -n 3p "$LINT_DIR/ultimo.md") Relatório: $LINT_DIR/ultimo.md"
exit "$CODIGO"
