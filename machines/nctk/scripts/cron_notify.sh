#!/bin/bash
# Уведомление в Telegram о событиях крона.
# Требует: BOT_TOKEN и LOG_GROUP_ID в ~/cron_notify.env

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${HOME}/cron_notify.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
fi
[[ -z "$LOG_GROUP_ID" && -n "$ALLOWED_CHAT_ID" ]] && LOG_GROUP_ID="$ALLOWED_CHAT_ID"

EVENT="${1:-start}"
TIME="${2:-$(date +%H:%M)}"
PEREMENA="${3:-?}"
TRACK="${4:-неизвестно}"
DURATION="${5:-}"
VOL="${6:-}"
DAY="${7:-}"
SUCCESS="${8:-}"

if [[ -z "$BOT_TOKEN" || -z "$LOG_GROUP_ID" ]]; then
    echo "Задайте BOT_TOKEN и LOG_GROUP_ID в $ENV_FILE" >&2
    exit 1
fi

TS="$(date '+%H:%M:%S %d.%m')"
FORMAT="${TRACK##*.}"
[[ -z "$FORMAT" || "$FORMAT" == "$TRACK" ]] && FORMAT="mp3"

DUR_FMT="—"
if [[ -n "$DURATION" && "$DURATION" =~ ^[0-9]+$ ]]; then
    DUR_FMT="$((DURATION/60)):$(printf '%02d' $((DURATION%60)))"
fi

if [[ "$EVENT" == "start" ]]; then
    MSG="⏰ [КРОН] Начало | ${DAY:+$DAY }${TIME}
📂 Трек: ${TRACK} (${FORMAT})
⏱ Длительность: ${DUR_FMT} (${DURATION:-—} сек)
🔊 Громкость: ${VOL:-—}%
🔄 ${PEREMENA}
${TS}"
else
    STATUS=""
    [[ "$SUCCESS" == "ok" ]] && STATUS="✅ Успешно"
    [[ "$SUCCESS" == "fail" ]] && STATUS="❌ Ошибка"
    MSG="⏹ [КРОН] Завершено | ${DAY:+$DAY }${TIME}
📂 Трек: ${TRACK}
${STATUS}
🔄 ${PEREMENA}
${TS}"
fi

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LOG_GROUP_ID}" \
    -d "text=${MSG}" \
    -d "disable_web_page_preview=true" \
    --max-time 10 >/dev/null || exit 1

echo "[${TS}] [КРОН] ${EVENT} | перемена ${PEREMENA} | ${TIME} | ${TRACK}" >> "${HOME}/action.log" 2>/dev/null || true
exit 0
