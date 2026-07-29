#!/bin/bash
# Диагностика: почему нет данных с client1 и client2
# Запускать на 10.10.4.120: bash scripts/diagnose-clients.sh

echo "=== 1. Prometheus слушает на 9091? ==="
ss -tlnp | grep 9091 || echo "нет"
echo ""

echo "=== 2. Доступность client1:9100 с хоста ==="
timeout 2 bash -c 'echo >/dev/tcp/10.20.0.41/9100' 2>/dev/null && echo "OK" || echo "FAIL"
echo ""

echo "=== 3. Доступность client2:9100 с хоста ==="
timeout 2 bash -c 'echo >/dev/tcp/10.70.0.41/9100' 2>/dev/null && echo "OK" || echo "FAIL"
echo ""

echo "=== 4. Loki на 3100 ==="
ss -tlnp | grep 3100 || echo "нет"
echo ""

echo "=== 5. Firewall — порты 3100, 9091 открыты? ==="
firewall-cmd --list-ports 2>/dev/null || echo "firewalld не используется"
