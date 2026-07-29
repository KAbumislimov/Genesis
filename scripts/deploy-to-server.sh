#!/bin/bash
# Деплой campus-infra на 10.10.4.120 (без remote-logs — они создаются на сервере)
# Запуск: bash scripts/deploy-to-server.sh

set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${1:-kamran@10.10.4.120}"

echo "=== Rsync (исключая remote-logs, .git) ==="
rsync -avz --exclude '.git' --exclude 'remote-logs' "$DIR/" "$SERVER:/home/kamran/campus-infra/"

echo ""
echo "=== Перезапуск Grafana и Promtail ==="
ssh "$SERVER" 'cd /home/kamran/campus-infra && docker compose --profile logs restart grafana promtail'

echo ""
echo "Готово. Grafana: http://10.10.4.120:3000"
