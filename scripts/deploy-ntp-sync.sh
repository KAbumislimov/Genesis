#!/bin/bash
# Деплой синхронизации времени: CentOS = NTP-сервер, client1 и client2 = клиенты.
# Запуск на сервере 10.10.4.120: bash campus-infra/scripts/deploy-ntp-sync.sh
#
# Клиенты без интернета — синхронизируются с CentOS.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
NTP_SERVER="${NTP_SERVER:-10.10.4.120}"

echo "=== Деплой синхронизации времени ==="
echo "NTP-сервер: $NTP_SERVER (CentOS)"
echo ""

# 1. Настройка сервера (если мы на CentOS)
if [ -f /etc/redhat-release ]; then
    echo "--- 1. Настройка NTP-сервера на CentOS ---"
    bash "$SCRIPT_DIR/setup-ntp-server-centos.sh"
    echo ""
else
    echo "--- 1. Пропуск (не CentOS). Запустите setup-ntp-server-centos.sh на CentOS вручную. ---"
    echo ""
fi

# 2. Настройка клиентов
echo "--- 2. Настройка NTP-клиентов (client1, client2) ---"

for client in "client1@10.20.0.41" "client2@10.70.0.41"; do
    echo "  $client..."
    scp $SSH_OPTS "$SCRIPT_DIR/setup-ntp-client.sh" "$client:/tmp/"
    ssh $SSH_OPTS "$client" "NTP_SERVER=$NTP_SERVER sudo bash /tmp/setup-ntp-client.sh" || echo "    Ошибка для $client"
done

echo ""
echo "--- 3. Проверка времени ---"
ssh $SSH_OPTS client1@10.20.0.41 "date '+client1:  %H:%M:%S %d.%m.%Y'" 2>/dev/null || echo "client1: недоступен"
ssh $SSH_OPTS client2@10.70.0.41 "date '+client2:   %H:%M:%S %d.%m.%Y'" 2>/dev/null || echo "client2: недоступен"
echo "Server: $(date '+%H:%M:%S %d.%m.%Y')"
echo ""
echo "Если расхождение — подождите 2–5 минут, chrony синхронизируется."
