#!/bin/bash
# Убеждается, что github-live-sync.sh жив; если нет — запускает заново.
# Вызывается из crontab: @reboot (старт после перезагрузки сервера) и
# каждые 5 минут (самовосстановление, если процесс почему-то упал).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/github-live-sync.sh"
PIDFILE="$HOME/log/github-live-sync.pid"
LOG="$HOME/log/github-live-sync.log"

mkdir -p "$(dirname "$PIDFILE")"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0  # уже работает
fi

nohup bash "$SYNC_SCRIPT" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
