# Inventário das máquinas

Resumo sem dados reais (sem IP, serial ou URL). O inventário completo, gerado por `deploy/inventario.sh`,
e a leitura do SMART ficam no vault, na nota `maquinas-do-assistente-pessoal` (o arquivo tem hostname, IP e
serial: não vai para o git).

## Roteiro

Para cada máquina: modelo, função, sistema e versão; CPU, RAM (tipo e slots livres), GPU; discos com uso,
partições e SMART (horas, setores realocados e pendentes, desgaste do SSD); rede; serviços e VMs; defeitos e
upgrades possíveis. Em Linux, `deploy/inventario.sh` junta tudo (só lê; precisa de `sudo` e do `smartmontools`);
no Proxmox, rode como root (`docs/IMPLANTACAO.md` B1). No Mac: `system_profiler SPHardwareDataType SPStorageDataType`.

| Máquina | Inventário | Situação |
|---|---|---|
| i7 (produção) | 2026-10-24 | feito |
| i5 (Proxmox) | — | **Pendente** (PLANO 1c.1) |
| MacBook Air M1 (teste) | — | só especificação, sem script |

## i7 — 2026-10-24

| Item | Valor |
|---|---|
| Modelo | HP EliteDesk 800 G2 SFF |
| CPU | Intel Core i7-6700 (4 núcleos, 8 threads, 3,4–4,0 GHz), VT-x, sem GPU dedicada |
| RAM | 16 GB DDR4-2133, 4 × 4 GB (os 4 slots ocupados, módulos de dois fabricantes); placa aceita até 64 GB |
| SSD | SanDisk SD8SBAT 256 GB, SATA: `/boot/efi`, `/` (ext4, 3% usado) e swap de 12 GB |
| HD | Seagate ST3500414CS 500 GB, 5900 rpm, SATA 3 Gb/s: `/srv/backup-hd`, só backup |
| Sistema | Debian 13, kernel 6.12, Docker; sem Proxmox |
| Containers | postgres 16, servidor do assistente, tailscale (Funnel) |
| Rede | 1 Ethernet gigabit (Intel I219-LM) na LAN, Tailscale |

### Saúde dos discos (smartctl, 2026-10-24)

| Disco | Horas | Leitura |
|---|---|---|
| SSD | 1038 | usável: realocado (5) = 1, incorrigível (187) = 2, reserva (232) = 99%. Vigiar 5 e 187 |
| HD | 5187 | teste longo sem erro (5169 h); realocado, pendente e incorrigível = 0; **End-to-End (184) = 25, FAILING_NOW**; CRC (199) = 13155, igual a 2026-10-23. Backup provisório; trocar quando der |

### Energia (powertop 30 s, ocioso com a stack, 2026-10-24)

- CPU em 4,1% de uso e 350 wakeups/s; os maiores são o timer do kernel, containerd, tailscaled e dockerd.
- Package C-states: pc7 50,5% e pc8 35,1% (C6 ou mais fundo em ~86% do tempo). Núcleos em cc7 ~96%.
- O `--auto-tune` está aplicado. Sobra só o link power management do SATA no `host4`.

### Pontos abertos

- Microcódigo: `intel-microcode` instalado, revisão `0xf0` (a última para o i7-6700). O `lscpu` continua com
  "Gather data sampling: Vulnerable: No microcode" porque a Intel não corrigiu o GDS para esse processador.
- Upgrade possível de RAM: só trocando módulos, porque os 4 slots estão ocupados.
