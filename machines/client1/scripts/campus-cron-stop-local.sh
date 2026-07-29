#!/bin/bash
# Локальная остановка воспроизведения — строго по времени
set -e
PLAYERCTL="${CAMPUS_PLAYERCTL:-/usr/local/bin/campus-playerctl}"
"$PLAYERCTL" stop 2>/dev/null || true
echo "[$(date '+%H:%M:%S %d.%m')] Cron stop local ($(hostname)): воспроизведение остановлено" >> "${LOG_FILE:-$HOME/action.log}" 2>/dev/null || true
