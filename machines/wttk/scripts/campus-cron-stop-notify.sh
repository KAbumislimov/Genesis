#!/bin/bash
# Zəngin dayandırılması + Telegram bildirişi.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$DIR/cron_notify.sh"

case "$(date +%u)" in
  1) DAY_AZ="B.e" ;; 2) DAY_AZ="Ç.a" ;; 3) DAY_AZ="Ç" ;;
  4) DAY_AZ="C.a" ;; 5) DAY_AZ="C" ;; 6) DAY_AZ="Ş" ;; 7) DAY_AZ="B" ;;
esac

"$DIR/campus-cron-stop-local.sh"

ENV_FILE="${HOME}/cron_notify.env"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }
if [[ -n "$BOT_TOKEN" && -n "$LOG_GROUP_ID" ]]; then
    LABEL_PREFIX=""
    [[ -n "$CAMPUS_LABEL" ]] && LABEL_PREFIX="🏫 ${CAMPUS_LABEL}
"
    MSG="${LABEL_PREFIX}⏹ [ZƏNG] Dayandırıldı | ${DAY_AZ} $(date +%H:%M)
🕒 $(date '+%H:%M:%S %d.%m.%Y')"
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${LOG_GROUP_ID}" \
        -d "text=${MSG}" \
        --max-time 10 >/dev/null || true
fi
exit 0
