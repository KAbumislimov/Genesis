#!/bin/bash
# Добавить синхронизацию времени в cron на CentOS.
# Запуск в 6:02, 16:02, 22:02 — вне учебного времени, не мешает переменам.
#
# Запуск: bash campus-infra/scripts/install-sync-time-cron.sh
set -e

SCRIPT="/home/kamran/campus-infra/scripts/sync-time-via-ssh.sh"
CRON_ENTRY="2 6,16,22 * * * $SCRIPT"

if crontab -l 2>/dev/null | grep -q "sync-time-via-ssh"; then
    echo "Запись уже есть в crontab"
else
    (crontab -l 2>/dev/null; echo "# Синхронизация времени client1/client2 с CentOS (вне учебного времени)"; echo "$CRON_ENTRY") | crontab -
    echo "Добавлено: $CRON_ENTRY"
fi
