#!/bin/bash
# Открыть порт 9091 (Prometheus) в firewalld
# Запускать на 10.10.4.120: sudo bash scripts/open-prometheus-port.sh

if command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --add-port=9091/tcp --permanent 2>/dev/null && sudo firewall-cmd --reload && echo "Порт 9091 открыт"
elif command -v ufw &>/dev/null; then
    sudo ufw allow 9091/tcp && sudo ufw reload && echo "Порт 9091 открыт"
else
    echo "firewalld/ufw не найден. Проверьте iptables вручную."
fi
