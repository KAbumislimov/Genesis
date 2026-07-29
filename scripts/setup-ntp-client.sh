#!/bin/bash
# Настройка NTP-клиента (client1 или client2) — синхронизация с CentOS.
# Запуск НА клиенте: sudo bash setup-ntp-client.sh
# Или с сервера: ssh client1@10.20.0.41 'sudo bash -s' < setup-ntp-client.sh
#
# NTP_SERVER — IP CentOS (по умолчанию 10.10.4.120)
set -e

NTP_SERVER="${NTP_SERVER:-10.10.4.120}"

echo "=== Настройка NTP-клиента (сервер: $NTP_SERVER) ==="

# Определяем ОС
if [ -f /etc/redhat-release ]; then
    CONF="/etc/chrony.conf"
elif [ -f /etc/debian_version ]; then
    CONF="/etc/chrony/chrony.conf"
elif [ -d /etc/chrony ]; then
    CONF="/etc/chrony/chrony.conf"
else
    CONF="/etc/chrony.conf"
fi

# Установка
if ! command -v chronyd &>/dev/null; then
    echo "Установка chrony..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y chrony
    else
        sudo yum install -y chrony 2>/dev/null || sudo dnf install -y chrony
    fi
fi

# Бэкап
sudo cp "$CONF" "${CONF}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true

# Конфиг клиента
sudo tee "$CONF" << EOF
# Синхронизация с CentOS (сервер без интернета у клиентов)
server $NTP_SERVER iburst prefer
maxpoll 6
minpoll 4

driftfile /var/lib/chrony/drift
makestep 0.1 3
rtcsync
EOF

(sudo systemctl enable chronyd 2>/dev/null || sudo systemctl enable chrony 2>/dev/null) || true
(sudo systemctl restart chronyd 2>/dev/null || sudo systemctl restart chrony 2>/dev/null) || true

echo ""
echo "Готово. Клиент синхронизируется с $NTP_SERVER"
echo "Проверка через несколько минут: chronyc sources"
