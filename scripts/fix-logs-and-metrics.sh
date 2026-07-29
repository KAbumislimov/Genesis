#!/bin/bash
# Восстановление логов и метрик: Grafana, Loki, Promtail, Prometheus, туннели nctk/vm1
# Запуск: cd /home/kamran/campus-infra && bash scripts/fix-logs-and-metrics.sh

set -e
cd "$(dirname "$0")/.."

PROFILES="--profile logs --profile bot --profile watchdog --profile recovery"

echo "=== 1. Текущие контейнеры ==="
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | grep -E 'loki|grafana|promtail|prometheus|node-exporter' || echo "(нет)"

echo ""
echo "=== 2. Запуск стека логов (Loki, Grafana, Promtail, Prometheus, node-exporter) ==="
docker compose $PROFILES up -d loki grafana promtail prometheus node-exporter

echo ""
echo "=== 3. Ожидание 15 сек ==="
sleep 15

echo ""
echo "=== 4. Статус контейнеров ==="
docker compose $PROFILES ps 2>/dev/null || true

echo ""
echo "=== 5. Grafana — если перезапускается, сбросим volume ==="
if docker ps -a --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q 'grafana.*Restarting'; then
    echo "Grafana в цикле перезапуска. Сброс volume..."
    docker compose --profile logs stop grafana 2>/dev/null || true
    docker rm -f grafana 2>/dev/null || true
    VOL=$(docker volume ls -q 2>/dev/null | grep grafana_data | head -1)
    [[ -n "$VOL" ]] && docker volume rm "$VOL" 2>/dev/null && echo "  Volume grafana_data удалён" || true
    docker compose $PROFILES up -d grafana
    echo "  Подождите 20 сек..."
    sleep 20
fi

echo ""
echo "=== 6. Проверка Loki (labels) ==="
curl -s -m 5 "http://127.0.0.1:3100/loki/api/v1/labels" 2>/dev/null | head -c 200 || echo "Loki не отвечает"

echo ""
echo "=== 7. Проверка Prometheus (targets) ==="
curl -s -m 5 "http://127.0.0.1:9091/api/v1/targets" 2>/dev/null | grep -o '"health":"[^"]*"' | head -5 || echo "Prometheus не отвечает"

echo ""
echo "=== 8. Туннели для nctk/vm1 (логи с удалённых машин) ==="
for svc in loki-tunnel-nctk loki-tunnel-vm1; do
    if systemctl is-active --quiet $svc 2>/dev/null; then
        echo "  $svc: active"
    else
        echo "  $svc: НЕ ЗАПУЩЕН — sudo systemctl start $svc"
    fi
done

echo ""
echo "=== Готово ==="
echo "Grafana:  http://10.10.4.120:3000  (admin / из .env GRAFANA_PASSWORD)"
echo "Loki:     http://10.10.4.120:3100/ready"
echo "Prometheus: http://10.10.4.120:9091"
echo ""
echo "Если туннели не запущены: sudo systemctl start loki-tunnel-nctk loki-tunnel-vm1"
echo "Если нет логов nctk/vm1: bash scripts/setup-loki-tunnels.sh"
