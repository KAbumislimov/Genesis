#!/bin/bash
# Быстрая проверка campus-сервисов и ботов
# Запуск: ./check-status.sh

echo "=== CAMPUS (tg-campus, promtail, watchdog, grafana, loki) ==="
docker ps -a --format "table {{.Names}}\t{{.Status}}" | head -1
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E "tg-campus|promtail|campus-watchdog|grafana|loki"

echo ""
echo "=== Другие боты/telegram ==="
docker ps -a --format "{{.Names}}\t{{.Status}}" | grep -iE "bot|telegram" | grep -v "tg-campus" || echo "(нет)"

echo ""
echo "=== Watchdog (последние логи) ==="
docker logs campus-watchdog 2>&1 | tail -5
