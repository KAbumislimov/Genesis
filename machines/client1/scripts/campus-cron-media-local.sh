#!/bin/bash
# Media: воспроизведение по расписанию. Папки: 1=пн..5=пт, 6-7=сб-вс→папка 1.
# Вызов: campus-cron-media-local.sh SLOT [VOL]
# VOL: 110 (client1 перемены), 130 (client2 перемены), 160 (гимн). Длительность — cron stop.
set -e
export PATH="/usr/local/bin:/usr/bin:/bin"
PLAYERCTL="${CAMPUS_PLAYERCTL:-/usr/local/bin/campus-playerctl}"
[ -x "$PLAYERCTL" ] || PLAYERCTL="campus-playerctl"

MEDIA="${MEDIA_ROOT:-$HOME/Media}"
INBOX="${CAMPUS_INBOX:-/var/lib/campus-player/inbox}"
LOG_FILE="${LOG_FILE:-$HOME/action.log}"
[ -w "$LOG_FILE" ] 2>/dev/null || LOG_FILE="/tmp/media-cron.log"

SLOT="${1:-}"
[ -n "$SLOT" ] || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: укажите слот" >> "$LOG_FILE"; exit 1; }
VOL="${2:-130}"

LOCK="/tmp/campus-cron-media.lock"
exec 9>"$LOCK"
flock -n 9 || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: уже выполняется, пропуск $SLOT" >> "$LOG_FILE"; exit 0; }

# Webui pause: touch ~/.cron_paused  to disable, rm ~/.cron_paused to re-enable
[ -f "$HOME/.cron_paused" ] && {
  echo "[$(date '+%H:%M:%S %d.%m')] Cron Media ($(hostname)): ⏸ пауза активна, пропуск $SLOT" >> "$LOG_FILE"
  exit 0
}

DAY=$(date +%u)
FOLDER="$DAY"
[ "$DAY" -gt 5 ] 2>/dev/null && FOLDER=1

if [ "$SLOT" = "himn" ]; then
  [ "$DAY" = "1" ] || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: himn только пн" >> "$LOG_FILE"; exit 0; }
  FOLDER=1
  "$PLAYERCTL" stop 2>>"$LOG_FILE" || true
  sleep 1
fi

FILE=""
if [ "$SLOT" = "himn" ]; then
  for f in "himn.mp3" "HIMN.mp3" "himn.wav" "HIMN.wav"; do
    [ -f "$MEDIA/$FOLDER/$f" ] && FILE="$MEDIA/$FOLDER/$f" && break
  done
else
  for ext in mp3 wav; do
    [ -f "$MEDIA/$FOLDER/${SLOT}.${ext}" ] && FILE="$MEDIA/$FOLDER/${SLOT}.${ext}" && break
  done
fi

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "[$(date '+%H:%M:%S %d.%m')] Cron Media ($(hostname)): нет $MEDIA/$FOLDER/${SLOT}" >> "$LOG_FILE"
  exit 0
fi

mkdir -p "$INBOX" 2>/dev/null || true
if cp -f "$FILE" "$INBOX/in.mp3" 2>>"$LOG_FILE"; then
  "$PLAYERCTL" vol "$VOL" 2>/dev/null || true
  PLAY_OK=""
  for attempt in 1 2 3; do
    if "$PLAYERCTL" play "$INBOX/in.mp3" 2>>"$LOG_FILE"; then
      PLAY_OK=1
      sleep 2
      "$PLAYERCTL" vol "$VOL" 2>/dev/null || true
      break
    fi
    [ $attempt -lt 3 ] && sleep 2
  done
else
  PLAY_OK=""
fi

STATUS="$([ -n "$PLAY_OK" ] && echo "✅" || echo "❌")"
echo "[$(date '+%H:%M:%S %d.%m')] Cron Media ($(hostname)): папка $FOLDER, $SLOT vol=$VOL $STATUS | $(basename "$FILE")" >> "$LOG_FILE"
exit 0
