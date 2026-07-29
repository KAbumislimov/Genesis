#!/bin/bash
# Настройка автозапуска мониторинга на campus-server (10.10.4.120)
# Запускать: ssh kamran@10.10.4.120 'bash -s' < scripts/install-auto-start.sh

set -e
cd "$(dirname "$0")/.."
DIR="$(pwd)"

echo "=== 1. Cron для sync-remote-logs ==="
bash scripts/install-sync-logs-cron.sh

echo ""
echo "=== 2. Docker Compose при загрузке (опционально) ==="
echo "Docker сервисы имеют restart: unless-stopped — запустятся после перезагрузки."
echo "Проверка: systemctl is-enabled docker"

echo ""
echo "=== 3. client1 и client2: node_exporter + promtail ==="
echo "На client1 и client2 выполните (один раз, с sudo):"
echo "  sudo cp /home/client1/promtail/node_exporter.service /etc/systemd/system/"
echo "  sudo cp /home/client1/promtail/promtail.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter promtail"
echo ""
echo "Или запустите: bash scripts/start-monitoring-on-clients.sh (без автозапуска)"
