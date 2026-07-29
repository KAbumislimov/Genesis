#!/bin/bash
SOCK="/run/campus-player/mpv.sock"
LOG="${LOG_FILE:-$HOME/action.log}"
[ -w "$LOG" ] 2>/dev/null || LOG="/tmp/landau-cron.log"

# Останавливаем ТОЛЬКО воспроизведение, не завершая mpv-процесс
if [ -S "$SOCK" ]; then
  echo '{"command":["stop"]}' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
fi

echo "[$(date '+%H:%M:%S %d.%m')] Cron stop local ($(hostname)): playback stopped (soft)" >> "$LOG"
