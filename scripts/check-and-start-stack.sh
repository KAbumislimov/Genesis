#!/bin/bash
# Диагностика и запуск стека Loki/Grafana/Prometheus на campus-server
# Запускать на 10.10.4.120: cd /home/kamran/campus-infra && bash scripts/check-and-start-stack.sh

set -e
cd "$(dirname "$0")/.."

echo "=== Проверка Docker ==="
docker --version || { echo "Docker не установлен"; exit 1; }

echo ""
echo "=== Текущие контейнеры ==="
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true

echo ""
echo "=== Запуск стека (Loki, Grafana, Promtail, Prometheus) ==="
docker compose --profile logs up -d

echo ""
echo "=== Статус через 5 сек ==="
sleep 5
docker compose --profile logs ps

echo ""
echo "=== Порты 3000, 3100, 9091 ==="
ss -tlnp 2>/dev/null | grep -E ':(3000|3100|9091)\s' || netstat -tlnp 2>/dev/null | grep -E ':(3000|3100|9091)\s' || echo "Проверьте вручную: ss -tlnp | grep -E '3000|3100|9091'"

echo ""
echo "Готово. Grafana: http://10.10.4.120:3000  Loki: :3100  Prometheus: :9091"
echo ""
echo "Если Grafana перезапускается (Restarting):"
echo "  docker compose --profile logs stop grafana"
echo "  docker volume rm campus-infra_grafana_data 2>/dev/null || docker volume rm \$(docker volume ls -q | grep grafana_data)"
echo "  docker compose --profile logs up -d grafana"
