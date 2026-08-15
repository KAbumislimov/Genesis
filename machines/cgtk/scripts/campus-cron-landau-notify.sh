#!/bin/bash
# Zəng/fasilə oxudulması + Telegram bildirişi (başladı/bitdi/buraxıldı).
# İstifadə: campus-cron-media-notify.sh SLOT [VOL]
# Əsas oxutma məntiqini DƏYİŞMİR — campus-cron-media-local.sh-ı olduğu kimi çağırır,
# sadəcə ətrafında bildiriş üçün metadata (fayl/ölçü/format) hesablayır.
set -e
export PATH="/usr/local/bin:/usr/bin:/bin"
DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIA="${MEDIA_ROOT:-$HOME/Media}"
NOTIFY="$DIR/cron_notify.sh"

SLOT="${1:-}"
VOL="${2:-130}"
[[ -n "$SLOT" ]] || exit 1

case "$(date +%u)" in
  1) DAY_AZ="B.e" ;; 2) DAY_AZ="Ç.a" ;; 3) DAY_AZ="Ç" ;;
  4) DAY_AZ="C.a" ;; 5) DAY_AZ="C" ;; 6) DAY_AZ="Ş" ;; 7) DAY_AZ="B" ;;
esac
TIME="$(date +%H:%M)"

case "$SLOT" in
  utro)   SLOT_NAME="Səhər musiqisi" ;;
  himn)   SLOT_NAME="Himn" ;;
  1peremena) SLOT_NAME="1-ci fasilə" ;;
  2peremena) SLOT_NAME="2-ci fasilə" ;;
  3peremena) SLOT_NAME="3-cü fasilə" ;;
  4peremena) SLOT_NAME="4-cü fasilə" ;;
  5peremena) SLOT_NAME="5-ci fasilə" ;;
  6peremena) SLOT_NAME="6-cı fasilə" ;;
  7peremena) SLOT_NAME="7-ci fasilə" ;;
  8peremena) SLOT_NAME="8-ci fasilə" ;;
  9peremena) SLOT_NAME="9-cu fasilə" ;;
  *)         SLOT_NAME="$SLOT" ;;
esac

# Pauza yoxlanışı (~/.cron_paused bayrağı, client1-dəki ilə eyni konvensiya).
# Qeyd: campus-cron-media-local.sh özü bu yoxlamanı etmir (yalnız notify
# skripti edir) — ona görə pauzada olanda əsas skripti heç çağırmırıq.
if [[ -f "$HOME/.cron_paused" ]]; then
    "$NOTIFY" skip "$TIME" "$DAY_AZ" "$SLOT_NAME" "" "" "" "" "Pauza aktivdir"
    exit 0
fi

DAY_NUM=$(date +%u)
FOLDER="$DAY_NUM"
[[ "$DAY_NUM" -gt 5 ]] && FOLDER=1
[[ "$SLOT" == "himn" ]] && FOLDER=1

FILE=""
if [[ "$SLOT" == "himn" ]]; then
    for f in himn.mp3 HIMN.mp3 himn.wav HIMN.wav; do
        [[ -f "$MEDIA/$FOLDER/$f" ]] && FILE="$MEDIA/$FOLDER/$f" && break
    done
else
    for ext in mp3 wav; do
        [[ -f "$MEDIA/$FOLDER/${SLOT}.${ext}" ]] && FILE="$MEDIA/$FOLDER/${SLOT}.${ext}" && break
    done
fi

if [[ -z "$FILE" ]]; then
    "$NOTIFY" skip "$TIME" "$DAY_AZ" "$SLOT_NAME" "" "" "" "" "Fayl tapılmadı ($MEDIA/$FOLDER/$SLOT)"
    exit 0
fi

TRACK="$(basename "$FILE")"
FORMAT="${TRACK##*.}"
SIZE_H="$(du -h "$FILE" 2>/dev/null | cut -f1)"
[[ -z "$SIZE_H" ]] && SIZE_H="—"

"$NOTIFY" start "$TIME" "$DAY_AZ" "$SLOT_NAME" "$TRACK" "$SIZE_H" "$FORMAT" "$VOL" &

# Log faylının yolu — campus-cron-media-local.sh-dəki məntiqin eynisi,
# ona görə nəticəni ordan (✅/❌) oxuya bilək, statusu təxmin etməyək
# (mpv qısa trek bitəndə "idle"-a qayıdır — statusa görə yoxlama yalan
# "uğursuz" verə bilər, halbuki səs həqiqətən oxudu).
CRON_LOG="${LOG_FILE:-$HOME/action.log}"
[[ -f "$CRON_LOG" ]] || touch "$CRON_LOG" 2>/dev/null
[[ -w "$CRON_LOG" ]] 2>/dev/null || CRON_LOG="/tmp/media-cron.log"

# Əsas (dəyişilməmiş) skripti çağırırıq — real oxutma məntiqi ordadır
RC=0
"$DIR/campus-cron-media-local.sh" "$SLOT" "$VOL" || RC=$?

SUCCESS="fail"
if [[ "$RC" -eq 0 ]] && tail -1 "$CRON_LOG" 2>/dev/null | grep -q '✅'; then
    SUCCESS="ok"
fi

"$NOTIFY" end "$(date +%H:%M)" "$DAY_AZ" "$SLOT_NAME" "$TRACK" "" "" "" "" "$SUCCESS" &
wait
exit "$RC"
