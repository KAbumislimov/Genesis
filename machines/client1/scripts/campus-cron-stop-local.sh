#!/bin/bash
SOCK="/run/campus-player/mpv.sock"
LOG="${LOG_FILE:-$HOME/action.log}"
[ -f "$LOG" ] || touch "$LOG" 2>/dev/null
[ -w "$LOG" ] 2>/dev/null || LOG="/tmp/landau-cron.log"

# Останавливаем ТОЛЬКО воспроизведение, не завершая mpv-процесс
# (раньше здесь был campus-playerctl stop → pkill -9 mpv — убивал процесс,
# что могло гоняться с одновременным ручным запуском/следующей переменой)
if [ -S "$SOCK" ]; then
  echo '{"command":["stop"]}' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
fi

echo "[$(date '+%H:%M:%S %d.%m')] Cron stop local ($(hostname)): playback stopped (soft)" >> "$LOG"
