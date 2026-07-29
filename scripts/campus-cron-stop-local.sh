#!/bin/bash
# Локальная остановка воспроизведения (для nctk/vm1 при локальном кроне).
# Вызов из cron без аргументов.
# ВАЖНО: campus-playerctl stop отправлял SIGKILL — используем IPC quit для корректной остановки.
SOCK="${CAMPUS_PLAYER_SOCKET:-/run/campus-player/mpv.sock}"
LOG="${LOG_FILE:-$HOME/action.log}"
[ -w "$LOG" ] 2>/dev/null || LOG="/tmp/landau-cron.log"

if [ -S "$SOCK" ]; then
  echo '{"command":["quit"]}' | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null || true
else
  # Fallback: campus-playerctl (может использовать kill -9)
  PLAYERCTL="${CAMPUS_PLAYERCTL:-/usr/local/bin/campus-playerctl}"
  [ -x "$PLAYERCTL" ] && "$PLAYERCTL" stop 2>/dev/null || true
fi
echo "[$(date '+%H:%M:%S %d.%m')] Cron stop local ($(hostname)): воспроизведение остановлено" >> "$LOG"
