#!/bin/bash
# Восстановление машины из последнего бэкапа
# Запуск: restore.sh <server|client1|client2>
# Внимание: для server — частичное восстановление (конфиги). Для client1/client2 — через SSH.

set -e
HOST_ID="${1:?Укажите: server|client1|client2}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUPS_ROOT="${BACKUPS_ROOT:-/backups}"
SSH_KEY="${SSH_KEY:-/root/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

LATEST=$(ls -td "$BACKUPS_ROOT/$HOST_ID"/*/ 2>/dev/null | head -1)
[[ -z "$LATEST" ]] && { echo "Нет бэкапов для $HOST_ID"; exit 1; }
echo "Восстановление из: $LATEST"

case "$HOST_ID" in
  server)
    HOST_ROOT="${HOST_ROOT:-/host}"
    echo "=== Восстановление server ==="
    [[ -f "$LATEST/etc.tar.gz" ]] && tar -xzf "$LATEST/etc.tar.gz" -C "$HOST_ROOT"
    [[ -f "$LATEST/home_kamran.tar.gz" ]] && tar -xzf "$LATEST/home_kamran.tar.gz" -C "$HOST_ROOT"
    [[ -f "$LATEST/root.tar.gz" ]] && tar -xzf "$LATEST/root.tar.gz" -C "$HOST_ROOT"
    [[ -d "$LATEST/cron" ]] && cp -a "$LATEST/cron"/* "$HOST_ROOT/var/spool/cron/" 2>/dev/null || true
    [[ -f "$LATEST/campus_infra.tar.gz" ]] && tar -xzf "$LATEST/campus_infra.tar.gz" -C "$HOST_ROOT/home/kamran"
    echo "Перезапуск Docker..."
    (cd "$HOST_ROOT/home/kamran/campus-infra" && (docker compose --profile logs --profile bot --profile watchdog --profile recovery up -d 2>/dev/null || docker-compose --profile logs --profile bot --profile watchdog --profile recovery up -d 2>/dev/null)) || true
    ;;
  client1|client2)
    USER="$HOST_ID"
    HOST=$([[ "$HOST_ID" == "client1" ]] && echo "10.20.0.41" || echo "10.70.0.41")
    [[ -f "$SSH_KEY" ]] && SSH_OPTS="-i $SSH_KEY $SSH_OPTS"
    echo "=== Восстановление $HOST_ID ($USER@$HOST) ==="
    if ! ssh $SSH_OPTS "${USER}@${HOST}" "true" 2>/dev/null; then
      echo "ОШИБКА: SSH до $HOST недоступен. Нужна полная переустановка (см. docs/RECOVERY.md)"
      exit 1
    fi
    cat "$LATEST/full_config.tar.gz" | ssh $SSH_OPTS "${USER}@${HOST}" "sudo tar -xzf - -C /" 2>/dev/null || \
    cat "$LATEST/full_config.tar.gz" | ssh $SSH_OPTS "${USER}@${HOST}" "tar -xzf - -C /" 2>/dev/null || true
    ssh $SSH_OPTS "${USER}@${HOST}" "sudo systemctl daemon-reload; sudo systemctl restart node_exporter promtail 2>/dev/null; sudo systemctl restart cron 2>/dev/null" || true
    echo "Восстановление завершено"
    ;;
  *)
    echo "Неизвестный хост: $HOST_ID"
    exit 1
    ;;
esac
