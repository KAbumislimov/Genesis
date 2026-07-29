#!/bin/bash
# Останавливает дубликаты ботов — оставляет по 1 экземпляру (systemd на сервере)
# Запуск на campus-server: bash scripts/stop-duplicate-bots.sh

set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "=== 1. Остановка Docker-ботов (дубликаты) ==="
docker stop tg-campus-bot tg-campus-genclik 2>/dev/null || true

echo ""
echo "=== 2. Отключение tg-narimanov (дубликат tg-campus-narimanov) ==="
sudo systemctl stop tg-narimanov.service 2>/dev/null || true
sudo systemctl disable tg-narimanov.service 2>/dev/null || true

echo ""
echo "=== 3. Проверка: оставшиеся боты (systemd) ==="
sudo systemctl is-active tg-campus-narimanov.service 2>/dev/null && echo "  tg-campus-narimanov: OK" || echo "  tg-campus-narimanov: не запущен"
sudo systemctl is-active tg-campus-genclik.service 2>/dev/null && echo "  tg-campus-genclik: OK" || echo "  tg-campus-genclik: не запущен"

echo ""
echo "=== 4. Запуск systemd-ботов (если не запущены) ==="
sudo systemctl start tg-campus-narimanov.service 2>/dev/null || true
sudo systemctl start tg-campus-genclik.service 2>/dev/null || true

echo ""
echo "=== 5. Watchdog не должен перезапускать Docker-боты ==="
echo "Добавьте в .env (если ещё нет):"
echo "  SERVER_CONTAINERS=promtail campus-watchdog campus-recovery"
echo ""

echo "Готово. Работают только tg-campus-narimanov и tg-campus-genclik (по 1 разу)."
echo "При следующем 'docker compose up' не используйте --profile bot."
