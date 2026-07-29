#!/bin/bash
# Исправление цикла перезапуска Grafana (image-renderer)
# Запускать: cd /home/kamran/campus-infra && bash scripts/fix-grafana-restart.sh

set -e
cd "$(dirname "$0")/.."

echo "=== Остановка и удаление контейнера Grafana ==="
docker compose --profile logs stop grafana
docker rm -f grafana 2>/dev/null || true

echo ""
echo "=== Удаление volume grafana_data (сброс плагинов и БД) ==="
VOL=$(docker volume ls -q | grep grafana_data | head -1)
if [[ -n "$VOL" ]]; then
    docker volume rm "$VOL"
    echo "Удалён: $VOL"
else
    echo "Volume grafana_data не найден"
fi

echo ""
echo "=== Запуск Grafana ==="
docker compose --profile logs up -d grafana

echo ""
echo "Подождите 10–15 сек, затем: docker ps | grep grafana"
echo "Grafana: http://10.10.4.120:3000"
