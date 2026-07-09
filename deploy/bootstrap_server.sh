#!/usr/bin/env bash
# DexCexMix server bootstrap. Usage: bootstrap_server.sh <role: data|exec|ctrl>
set -euo pipefail
ROLE="${1:?role required: data|exec|ctrl}"

# --- 8G swap + swappiness=10 (coin 内存加固方法论) ---
if ! sudo swapon --show | grep -q '/swapfile'; then
  sudo dd if=/dev/zero of=/swapfile bs=1M count=8192 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
printf 'vm.swappiness=10\n' | sudo tee /etc/sysctl.d/99-dexcexmix.conf >/dev/null
sudo sysctl -q -p /etc/sysctl.d/99-dexcexmix.conf

# --- base packages ---
sudo dnf -y -q install git htop python3.11 python3.11-pip >/dev/null

# --- dexcexmix.slice: 服务统一挂载点, 给 OS 留余量 ---
TOTAL_G=$(free -g | awk '/Mem:/{print $2}')
MEMMAX=12G
if [ "$TOTAL_G" -le 8 ]; then MEMMAX=6G; fi
sudo tee /etc/systemd/system/dexcexmix.slice >/dev/null <<UNIT
[Unit]
Description=DexCexMix services slice
[Slice]
MemoryMax=${MEMMAX}
UNIT
sudo systemctl daemon-reload

mkdir -p ~/dexcexmix ~/logs

case "$ROLE" in
  data)
    sudo dnf -y -q install redis6 postgresql16-server postgresql16 >/dev/null
    # Redis 总线: SG 保护下开内网, maxmemory 防挤压时序库
    sudo sed -i 's/^bind .*/bind 0.0.0.0 -::1/' /etc/redis6/redis6.conf
    sudo sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis6/redis6.conf
    grep -q '^maxmemory ' /etc/redis6/redis6.conf || printf 'maxmemory 2gb\nmaxmemory-policy noeviction\n' | sudo tee -a /etc/redis6/redis6.conf >/dev/null
    sudo systemctl enable --now redis6
    ;;
  ctrl)
    sudo dnf -y -q install postgresql16-server postgresql16 >/dev/null
    ;;
  exec)
    : # 执行面只要基础件
    ;;
esac

# --- Postgres (data=时序库 / ctrl=统一OLTP库) ---
if [ "$ROLE" = "data" ] || [ "$ROLE" = "ctrl" ]; then
  if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
    sudo postgresql-setup --initdb >/dev/null
  fi
  PGCONF=/var/lib/pgsql/data/postgresql.conf
  grep -q "^listen_addresses" $PGCONF || printf "listen_addresses = '*'\n" | sudo tee -a $PGCONF >/dev/null
  PGHBA=/var/lib/pgsql/data/pg_hba.conf
  grep -q '10.0.1.0/24' $PGHBA || printf 'host    all    all    10.0.1.0/24    scram-sha-256\n' | sudo tee -a $PGHBA >/dev/null
  sudo systemctl enable --now postgresql
fi

echo "BOOTSTRAP_OK role=$ROLE swap=$(swapon --show --noheadings | awk '{print $3}') slice=$MEMMAX"
