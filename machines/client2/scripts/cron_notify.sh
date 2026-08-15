#!/bin/bash
# Telegram bildirişi (fasilə/zəng başlayanda və bitəndə).
# Tələb olunur: BOT_TOKEN və LOG_GROUP_ID faylı ~/cron_notify.env
set -e
ENV_FILE="${HOME}/cron_notify.env"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

EVENT="${1:-start}"      # start | end | skip
TIME="${2:-$(date +%H:%M)}"
DAY_AZ="${3:-}"
SLOT_NAME="${4:-?}"
TRACK="${5:-naməlum}"
SIZE_H="${6:-—}"
FORMAT="${7:-mp3}"
VOL="${8:-—}"
REASON="${9:-}"          # skip üçün: pauza / fayl yoxdur
SUCCESS="${10:-}"        # end üçün: ok / fail

[[ -z "$BOT_TOKEN" || -z "$LOG_GROUP_ID" ]] && exit 0

TS="$(date '+%H:%M:%S %d.%m.%Y')"

case "$EVENT" in
  start)
    MSG="🔔 [ZƏNG] Başladı | ${DAY_AZ} ${TIME}
🔄 Fasilə: ${SLOT_NAME}
📂 Fayl: ${TRACK}
📦 Ölçü: ${SIZE_H}
🎵 Format: ${FORMAT}
🔊 Səs həcmi: ${VOL}%
🕒 ${TS}"
    ;;
  end)
    STATUS="✅ Uğurla oxudu"
    [[ "$SUCCESS" != "ok" ]] && STATUS="❌ Xəta — səs çıxmadı"
    MSG="⏹ [ZƏNG] Bitdi | ${DAY_AZ} ${TIME}
🔄 Fasilə: ${SLOT_NAME}
📂 Fayl: ${TRACK}
${STATUS}
🕒 ${TS}"
    ;;
  skip)
    MSG="⏸ [ZƏNG] Buraxıldı | ${DAY_AZ} ${TIME}
🔄 Fasilə: ${SLOT_NAME}
❗ Səbəb: ${REASON}
🕒 ${TS}"
    ;;
  *)
    exit 0
    ;;
esac

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LOG_GROUP_ID}" \
    -d "text=${MSG}" \
    -d "disable_web_page_preview=true" \
    --max-time 10 >/dev/null || true
exit 0
