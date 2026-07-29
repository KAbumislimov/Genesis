#!/bin/bash
# Диагностика стека Loki/Prometheus/Grafana
# Запуск: bash scripts/check-logs-stack.sh

cd "$(dirname "$0")/.."

echo "=== 1. Статус контейнеров ==="
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E 'loki|prometheus|grafana|promtail|node-exporter' || true

echo ""
echo "=== 2. Loki (порт 3100) ==="
curl -s -o /dev/null -w "%{http_code}" http://localhost:3100/ready && echo " OK" || echo " FAIL"

echo ""
echo "=== 3. Prometheus (порт 9091, host) ==="
curl -s -o /dev/null -w "%{http_code}" http://localhost:9091/-/healthy && echo " OK" || echo " FAIL"

echo ""
echo "=== 4. Node Exporter (порт 9100) ==="
curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics | head -c 3 && echo " OK" || echo " FAIL"

echo ""
echo "=== 5. Targets Prometheus ==="
curl -s "http://localhost:9091/api/v1/targets" 2>/dev/null | grep -o '"health":"[^"]*"' | sort | uniq -c || echo "Prometheus не отвечает"

echo ""
echo "=== 6. Последние логи Loki ==="
docker logs loki --tail 5 2>&1 || true

echo ""
echo "=== 7. Последние логи Prometheus ==="
docker logs prometheus --tail 5 2>&1 || true
