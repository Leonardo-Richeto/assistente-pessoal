#!/usr/bin/env bash
# Inventário da máquina, só leitura. Roda em Linux (host Proxmox, VM ou i7).
# Grava inventario-<hostname>-<AAAA-MM-DD>.md no diretório atual. Nada sai pela rede.
# Falta de ferramenta vira "não disponível". Rode como root para ver RAM (dmidecode) e SMART completos.
#   sudo bash deploy/inventario.sh
set -u

HOST="$(hostname 2>/dev/null || echo desconhecido)"
DATA="$(date +%F)"
SAIDA="inventario-${HOST}-${DATA}.md"

tem() { command -v "$1" >/dev/null 2>&1; }

# Roda um comando e põe a saída num bloco. Sem a ferramenta, escreve "não disponível".
bloco() {
  local titulo="$1"; shift
  {
    echo
    echo "### ${titulo}"
    echo
    if ! tem "$1"; then
      echo "não disponível (\`$1\` não está instalado)"
      return
    fi
    echo '```'
    "$@" 2>&1 || echo "(o comando terminou com erro)"
    echo '```'
  } >>"$SAIDA"
}

# Igual a bloco, mas só roda como root.
bloco_root() {
  local titulo="$1"; shift
  if [ "$(id -u)" -ne 0 ]; then
    { echo; echo "### ${titulo}"; echo; echo "não disponível (precisa de root)"; } >>"$SAIDA"
    return
  fi
  bloco "$titulo" "$@"
}

{
  echo "# Inventário de ${HOST} — ${DATA}"
  echo
  echo "Gerado por \`deploy/inventario.sh\`. Só leitura; nada saiu da máquina."
  echo "Este arquivo tem hostname e IP reais: **não vai para o git**."
  echo
  echo "## Identificação"
  echo
  echo "- Hostname: ${HOST}"
  echo "- Usuário: $(id -un 2>/dev/null) (uid $(id -u))"
  echo "- Kernel: $(uname -sr 2>/dev/null)"
  echo "- Arquitetura: $(uname -m 2>/dev/null)"
  if [ -r /etc/os-release ]; then
    echo "- SO: $(. /etc/os-release && echo "${PRETTY_NAME:-desconhecido}")"
  else
    echo "- SO: não disponível"
  fi
  if tem systemd-detect-virt; then
    echo "- Virtualização: $(systemd-detect-virt 2>/dev/null || true)"
  else
    echo "- Virtualização: não disponível"
  fi
  echo "- Tempo ligado: $(uptime -p 2>/dev/null || echo 'não disponível')"
  if [ -r /sys/class/dmi/id/product_name ]; then
    echo "- Modelo (DMI): $(cat /sys/class/dmi/id/sys_vendor 2>/dev/null) $(cat /sys/class/dmi/id/product_name 2>/dev/null)"
  fi
  echo
  echo "## CPU"
} >"$SAIDA"
bloco "lscpu" lscpu

echo -e "\n## Memória" >>"$SAIDA"
bloco "free -h" free -h
bloco_root "dmidecode -t memory (tipo, velocidade e slots)" dmidecode -t memory

echo -e "\n## Discos" >>"$SAIDA"
bloco "lsblk" lsblk -o NAME,SIZE,MODEL,ROTA,TYPE,FSTYPE,MOUNTPOINT
bloco "df -h (sem tmpfs)" df -h -x tmpfs -x devtmpfs -x squashfs

if tem smartctl; then
  if [ "$(id -u)" -ne 0 ]; then
    { echo; echo "### SMART"; echo; echo "não disponível (precisa de root)"; } >>"$SAIDA"
  else
    # Só discos físicos (TYPE=disk), sem loop, ram nem zvol.
    DISCOS="$(lsblk -dn -o NAME,TYPE 2>/dev/null | awk '$2=="disk"{print $1}')"
    if [ -z "$DISCOS" ]; then
      { echo; echo "### SMART"; echo; echo "não disponível (nenhum disco físico encontrado)"; } >>"$SAIDA"
    fi
    for d in $DISCOS; do
      bloco "smartctl -a /dev/${d}" smartctl -a "/dev/${d}"
      bloco "smartctl -j -a /dev/${d} (JSON)" smartctl -j -a "/dev/${d}"
    done
  fi
else
  { echo; echo "### SMART"; echo; echo "não disponível (\`smartctl\` não está instalado; instale o pacote smartmontools)"; } >>"$SAIDA"
fi

echo -e "\n## Rede" >>"$SAIDA"
bloco "ip -br a" ip -br a

echo -e "\n## Proxmox" >>"$SAIDA"
if ! tem qm && ! tem pct && ! tem pvesm; then
  echo -e "\nnão disponível (esta máquina não é um host Proxmox)" >>"$SAIDA"
fi
bloco "qm list (VMs)" qm list
bloco "pct list (containers LXC)" pct list
bloco "pvesm status (armazenamento)" pvesm status

echo -e "\n## Docker" >>"$SAIDA"
bloco "docker ps" docker ps

echo "Inventário gravado em: $(pwd)/${SAIDA}"
