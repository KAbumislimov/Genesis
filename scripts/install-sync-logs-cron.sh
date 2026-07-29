#!/bin/bash
# Установка cron для копирования логов с nctk и vm1
# Запускать на 10.10.4.120: bash scripts/install-sync-logs-cron.sh

DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRON_CMD="* * * * * $DIR/scripts/sync-remote-logs.sh"
(crontab -l 2>/dev/null | grep -v sync-remote-logs; echo "$CRON_CMD") | crontab -
echo "Cron добавлен: каждую минуту sync-remote-logs.sh"
echo "Проверка: crontab -l"
