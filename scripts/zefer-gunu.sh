#!/bin/bash
# Zəfər Günü (8 noyabr) — раз в год запускает трек на всех зарегистрированных
# аудио-кампусах через /api/zefer-all. Не завязан на конкретные машины: любой
# кампус, добавленный через /machines к 8 ноября, получит его автоматически,
# т.к. эндпоинт сам перебирает music_machines() на момент вызова.
# Вызывается из crontab только 8 ноября (см. campus-infra crontab).
set -uo pipefail

TOKEN="${ZEFER_CRON_TOKEN:-knT5FWZ6-MLfF6BCSyiOY6vh013df5VR_wvdbZ4FWy4}"
URL="https://localhost:8090/api/zefer-all"
LOG="$HOME/log/zefer-gunu.log"
mkdir -p "$(dirname "$LOG")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Zəfər Günü — вызываю $URL" >> "$LOG"
curl -sk -X POST "$URL" -H "X-Cron-Token: $TOKEN" >> "$LOG" 2>&1
echo "" >> "$LOG"
