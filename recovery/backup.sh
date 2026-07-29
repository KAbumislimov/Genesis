#!/bin/bash
# Создание бэкапа машины (конфиги, сервисы, скрипты, кроны, боты)
# Запуск: backup.sh <server|client1|client2>

set -e
HOST_ID="${1:?Укажите: server|client1|client2}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUPS_ROOT="${BACKUPS_ROOT:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUPS_ROOT/$HOST_ID/$TIMESTAMP"
SSH_KEY="${SSH_KEY:-}"
[[ -z "$SSH_KEY" ]] && [[ -f /root/.ssh/campus_bot ]] && SSH_KEY="/root/.ssh/campus_bot"
[[ -z "$SSH_KEY" ]] && [[ -f /root/.ssh/id_rsa ]] && SSH_KEY="/root/.ssh/id_rsa"
SSH_OPTS="-F /dev/null -o StrictHostKeyChecking=no -o ConnectTimeout=30"
BACKUP_KEEP="${BACKUP_KEEP:-3}"

mkdir -p "$DEST"

case "$HOST_ID" in
  server)
    # Бэкап сервера (монтируется /host с хоста)
    HOST_ROOT="${HOST_ROOT:-/host}"
    echo "=== Бэкап server ==="
    [[ -d "$HOST_ROOT/etc" ]] && tar -czf "$DEST/etc.tar.gz" -C "$HOST_ROOT" etc 2>/dev/null || true
    [[ -d "$HOST_ROOT/home/kamran" ]] && tar -czf "$DEST/home_kamran.tar.gz" -C "$HOST_ROOT" home/kamran 2>/dev/null || true
    [[ -d "$HOST_ROOT/root" ]] && tar -czf "$DEST/root.tar.gz" -C "$HOST_ROOT" root 2>/dev/null || true
    [[ -d "$HOST_ROOT/var/spool/cron" ]] && cp -a "$HOST_ROOT/var/spool/cron" "$DEST/" 2>/dev/null || true
    if [[ -d "$HOST_ROOT/home/kamran/campus-infra" ]]; then
      tar -czf "$DEST/campus_infra.tar.gz" -C "$HOST_ROOT/home/kamran" campus-infra \
        --exclude='campus-infra/remote-logs' --exclude='campus-infra/.git' 2>/dev/null || true
    fi
    ;;
  client1|client2)
    USER="$HOST_ID"
    HOST=$(grep -A5 "^  $HOST_ID:" "$SCRIPT_DIR/config/hosts.yaml" 2>/dev/null | grep "host:" | head -1 | awk '{print $2}')
    [[ -z "$HOST" ]] && HOST=$([[ "$HOST_ID" == "client1" ]] && echo "10.20.0.41" || echo "10.70.0.41")
    echo "=== Бэкап $HOST_ID ($USER@$HOST) ==="
    [[ -f "$SSH_KEY" ]] && SSH_OPTS="-i $SSH_KEY $SSH_OPTS"
    ssh $SSH_OPTS "${USER}@${HOST}" "sudo tar -czf - -C / etc home/$USER root var/spool/cron 2>/dev/null" > "$DEST/full_config.tar.gz" 2>/dev/null || \
    ssh $SSH_OPTS "${USER}@${HOST}" "tar -czf - -C / etc home/$USER root var/spool/cron 2>/dev/null" > "$DEST/full_config.tar.gz" 2>/dev/null || true
    ;;
  *)
    echo "Неизвестный хост: $HOST_ID"
    exit 1
    ;;
esac

echo "Бэкап сохранён: $DEST"
ls -la "$DEST"

# Ротация: оставляем последние $BACKUP_KEEP бэкапов
OLD=$(ls "$BACKUPS_ROOT/$HOST_ID" 2>/dev/null | sort | head -n -"$BACKUP_KEEP")
if [[ -n "$OLD" ]]; then
  echo "$OLD" | xargs -I{} rm -rf "$BACKUPS_ROOT/$HOST_ID/{}"
  echo "Ротация: удалено $(echo "$OLD" | wc -l) старых бэкапов $HOST_ID"
fi

# Копирование на client1 (SSD) — если доступен
CLIENT1_BACKUPS="/mnt/campus-data/backups"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="-F /dev/null -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30"
if [[ -n "$SYNC_BACKUPS_TO_CLIENT1" ]] && [[ "$SYNC_BACKUPS_TO_CLIENT1" != "0" ]]; then
    if ssh $SSH_OPTS client1@10.20.0.41 "mkdir -p $CLIENT1_BACKUPS/$HOST_ID 2>/dev/null; test -w $CLIENT1_BACKUPS" 2>/dev/null; then
        rsync -az -e "ssh $SSH_OPTS" "$DEST/" "client1@10.20.0.41:$CLIENT1_BACKUPS/$HOST_ID/$TIMESTAMP/" 2>/dev/null && echo "Синхронизировано на client1:$CLIENT1_BACKUPS" || true
    fi
fi
