#!/bin/bash
# Устанавливает cron для kill-duplicate-bots.sh (каждую минуту)
# Запуск на campus-server (10.10.4.120): bash scripts/install-kill-duplicate-bots-cron.sh

set -e
cd "$(dirname "$0")/.."
SCRIPT="$(pwd)/scripts/kill-duplicate-bots.sh"
[[ ! -f "$SCRIPT" ]] && { echo "Не найден: $SCRIPT"; exit 1; }
chmod +x "$SCRIPT"
(crontab -l 2>/dev/null | grep -v kill-duplicate-bots; echo "* * * * * $SCRIPT 2>/dev/null") | crontab -
echo "Cron добавлен: каждую минуту kill-duplicate-bots.sh"
