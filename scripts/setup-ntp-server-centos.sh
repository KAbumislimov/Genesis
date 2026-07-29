#!/bin/bash
# Настройка CentOS (10.10.4.120) как NTP-сервер для клиентов без интернета.
# CentOS синхронизируется с pool.ntp.org (если есть интернет) или работает как эталон.
#
# Запуск на CentOS: sudo bash setup-ntp-server-centos.sh
set -e

CHRONY_CONF="/etc/chrony.conf"
CHRONY_BACKUP="${CHRONY_CONF}.bak.$(date +%Y%m%d%H%M%S)"

echo "=== Настройка NTP-сервера на CentOS ==="

# Проверка chrony
if ! command -v chronyd &>/dev/null; then
    echo "Установка chrony..."
    sudo yum install -y chrony 2>/dev/null || sudo dnf install -y chrony
fi

# Бэкап
sudo cp "$CHRONY_CONF" "$CHRONY_BACKUP"

# Конфиг: сервер + разрешить клиентам из локальной сети
sudo tee "$CHRONY_CONF" << 'EOF'
# Внешние источники (если есть интернет)
pool pool.ntp.org iburst maxsources 4

# Если нет интернета — использовать только local:
# local stratum 10

# Разрешить клиентам из локальной сети
allow 10.0.0.0/8
allow 192.168.0.0/16
allow 172.16.0.0/12

# Резерв: локальные часы, если нет upstream
local stratum 8

driftfile /var/lib/chrony/drift
makestep 0.1 3
rtcsync
EOF

echo "Открытие порта 123/udp в firewall..."
sudo firewall-cmd --add-service=ntp --permanent 2>/dev/null && sudo firewall-cmd --reload 2>/dev/null || true

sudo systemctl enable chronyd
sudo systemctl restart chronyd

echo ""
echo "Готово. NTP-сервер запущен."
echo "Клиенты должны использовать: server 10.10.4.120 iburst"
echo ""
echo "Проверка: chronyc sources"
