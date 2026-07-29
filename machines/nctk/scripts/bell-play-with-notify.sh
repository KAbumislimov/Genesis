#!/bin/bash
# Обёртка для воспроизведения с уведомлением в Telegram.
# Формат вызова: bell-play-with-notify.sh /path/to/file.mp3 [duration]

FILE="${1:-}"
DURATION="${2:-}"
VOL="${VOL:-—}"
[[ -n "$FILE" ]] && TRACK="$(basename "$FILE" 2>/dev/null)" || TRACK="bell.mp3"
[[ -z "$TRACK" ]] && TRACK="bell.mp3"

BASE="${TRACK%.*}"
case "$BASE" in
    utro)           PEREMENA="утро" ;;
    hymn|himn)      PEREMENA="гимн" ;;
    1peremena)      PEREMENA="1-я перемена" ;;
    2peremena)      PEREMENA="2-я перемена" ;;
    3peremena)      PEREMENA="3-я перемена" ;;
    4peremena)      PEREMENA="4-я перемена" ;;
    5peremena)      PEREMENA="5-я перемена" ;;
    6peremena)      PEREMENA="6-я перемена" ;;
    7peremena)      PEREMENA="7-я перемена" ;;
    8peremena)      PEREMENA="8-я перемена" ;;
    9peremena)      PEREMENA="9-я перемена" ;;
    *)              PEREMENA="${BASE}";;
esac

case "$(date +%u)" in
    1) DAY="Пн" ;; 2) DAY="Вт" ;; 3) DAY="Ср" ;;
    4) DAY="Чт" ;; 5) DAY="Пт" ;; 6) DAY="Сб" ;; 7) DAY="Вс" ;; *) DAY="" ;;
esac

TIME="$(date +%H:%M)"

/home/nctk/cron_notify.sh start "$TIME" "$PEREMENA" "$TRACK" "$DURATION" "$VOL" "$DAY" 2>/dev/null || true

RC=0
if [[ -x /usr/local/bin/bell-play.sh ]]; then
    /usr/local/bin/bell-play.sh "$@" || RC=$?
elif [[ -x /home/nctk/bell-play.sh ]]; then
    /home/nctk/bell-play.sh "$@" || RC=$?
else
    campus-playerctl play /var/lib/campus-player/inbox/in.mp3 70 2>/dev/null || RC=$?
fi

SUCCESS="ok"
[[ $RC -ne 0 ]] && SUCCESS="fail"
/home/nctk/cron_notify.sh end "$(date +%H:%M)" "$PEREMENA" "$TRACK" "$DURATION" "$VOL" "$DAY" "$SUCCESS" 2>/dev/null || true
exit $RC
