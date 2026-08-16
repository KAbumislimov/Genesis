#!/bin/bash
# Media: воспроизведение по расписанию. Папки: 1=пн..5=пт, 6-7=сб-вс→папка 1.
# Вызов: campus-cron-media-local.sh SLOT [VOL]
# VOL: 110 (client1 перемены), 130 (wttk перемены), 160 (гимн). Длительность — cron stop.
# Использует прямой IPC (socat) вместо campus-playerctl — избегаем SIGKILL.
set -e
export PATH="/usr/local/bin:/usr/bin:/bin"
SOCK="${CAMPUS_PLAYER_SOCKET:-/run/campus-player/mpv.sock}"

# Отправка JSON в mpv
mpv_ipc() {
  [ -S "$SOCK" ] || return 1
  echo "$1" | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null | grep -q '"error":"success"'
}

# Ждём сокет mpv (user-сервис может стартовать на 5–15 сек позже cron)
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  [ -S "$SOCK" ] && break
  sleep 1
done

MEDIA="${MEDIA_ROOT:-$HOME/Media}"
LOG_FILE="${LOG_FILE:-$HOME/action.log}"
[ -f "$LOG_FILE" ] || touch "$LOG_FILE" 2>/dev/null
[ -w "$LOG_FILE" ] 2>/dev/null || LOG_FILE="/tmp/media-cron.log"

SLOT="${1:-}"
[ -n "$SLOT" ] || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: укажите слот" >> "$LOG_FILE"; exit 1; }
VOL="${2:-130}"

# Блокировка — не запускать параллельно
LOCK="/tmp/campus-cron-media.lock"
exec 9>"$LOCK"
flock -n 9 || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: уже выполняется, пропуск $SLOT" >> "$LOG_FILE"; exit 0; }

# День 1=пн..7=вс; папки 1-5, сб-вс → папка 1
DAY=$(date +%u)
FOLDER="$DAY"
[ "$DAY" -gt 5 ] 2>/dev/null && FOLDER=1

# himn только понедельник
if [ "$SLOT" = "himn" ]; then
  [ "$DAY" = "1" ] || { echo "[$(date '+%H:%M:%S %d.%m')] Cron Media: himn только пн" >> "$LOG_FILE"; exit 0; }
  FOLDER=1
fi

FILE=""
# himn: пробуем himn.mp3, затем HIMN.mp3 (Linux case-sensitive)
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

# Воспроизведение через прямой IPC (без campus-playerctl)
FILE_ESC=$(printf '%s' "$FILE" | sed 's/\\/\\\\/g; s/"/\\"/g')
PLAY_OK=""
for attempt in 1 2 3; do
  # Громкость до загрузки файла на некоторых старых версиях mpv недоступна
  # ("property unavailable", пока нет активного трека) — не блокируем этим
  # loadfile через &&, громкость всё равно переустанавливается ниже после
  # старта воспроизведения.
  mpv_ipc "{\"command\":[\"set_property\",\"volume\",$VOL]}" 2>>"$LOG_FILE" || true
  if mpv_ipc "{\"command\":[\"loadfile\",\"$FILE_ESC\",\"replace\"]}" 2>>"$LOG_FILE"; then
    PLAY_OK=1
    sleep 2
    mpv_ipc "{\"command\":[\"set_property\",\"volume\",$VOL]}" 2>/dev/null || true
    break
  fi
  [ $attempt -lt 3 ] && sleep 2
done

STATUS="$([ -n "$PLAY_OK" ] && echo "✅" || echo "❌")"
echo "[$(date '+%H:%M:%S %d.%m')] Cron Media ($(hostname)): папка $FOLDER, $SLOT vol=$VOL $STATUS | $(basename "$FILE")" >> "$LOG_FILE"
exit 0
