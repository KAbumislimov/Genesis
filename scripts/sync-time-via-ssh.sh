#!/bin/bash
# Резервная синхронизация времени через SSH (если NTP недоступен).
# CentOS SSHs к клиентам и устанавливает своё время.
#
# БЕЗОПАСНО для cron и музыки на переменах:
# - Синхронизация только при расхождении > 30 сек
# - Запуск в 6:02, 16:02, 22:02 — вне учебного времени (7:45–15:15)
#
# Cron на CentOS: 2 6,16,22 * * * /home/kamran/campus-infra/scripts/sync-time-via-ssh.sh
set -e

KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=5"
REF_TS=$(date +%s)
REF_TIME=$(date '+%Y-%m-%d %H:%M:%S')

for client in "client1@10.20.0.41" "client2@10.70.0.41"; do
    REMOTE_TS=$(ssh $SSH_OPTS "$client" "date +%s" 2>/dev/null) || continue
    DIFF=$((REF_TS - REMOTE_TS))
    DIFF=${DIFF#-}  # abs
    if [ "$DIFF" -gt 30 ]; then
        ssh $SSH_OPTS "$client" "sudo timedatectl set-ntp false 2>/dev/null; sudo date -s '$REF_TIME'" 2>/dev/null || true
    fi
done
