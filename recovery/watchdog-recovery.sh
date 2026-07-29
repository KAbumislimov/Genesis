#!/bin/bash
# Recovery Watchdog: мониторит server, client1, client2. При сбое определяет машину и восстанавливает.
# Server (CentOS) управляет всеми. Запускается в Docker на 10.10.4.120.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUPS_ROOT="${BACKUPS_ROOT:-/backups}"
INTERVAL="${RECOVERY_CHECK_INTERVAL:-300}"
SSH_KEY="${SSH_KEY:-/root/.ssh/campus_bot}"
SSH_BASE_OPTS="-F /dev/null -o StrictHostKeyChecking=no -o BatchMode=yes"
SSH_OPTS="$SSH_BASE_OPTS -o ConnectTimeout=5"
ISSUES=()

# Пароли для SSH (если ключи не настроены) — из env
RECOVERY_CLIENT2_PASS="${RECOVERY_CLIENT2_PASS:-}"
RECOVERY_CLIENT1_PASS="${RECOVERY_CLIENT1_PASS:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
add_issue() { ISSUES+=("$1"); }

# Проверка доступности хоста
check_host() {
  local user="$1" host="$2"
  local opts="$SSH_BASE_OPTS -o ConnectTimeout=5"
  [[ -f "$SSH_KEY" ]] && opts="-i $SSH_KEY $opts"
  ssh $opts "${user}@${host}" "true" 2>/dev/null
}

# Проверка ping
check_ping() {
  ping -c 1 -W 3 "$1" &>/dev/null
}

# Перезапуск сервисов на удалённом хосте
restart_remote_services() {
  local host="$1" user="$2"
  shift 2
  local services=("$@")
  local opts="$SSH_BASE_OPTS -o ConnectTimeout=10"
  [[ -f "$SSH_KEY" ]] && opts="-i $SSH_KEY $opts"
  for svc in "${services[@]}"; do
    if ssh $opts "${user}@${host}" "systemctl is-enabled $svc 2>/dev/null" &>/dev/null; then
      if ! ssh $opts "${user}@${host}" "systemctl is-active --quiet $svc 2>/dev/null" 2>/dev/null; then
        log "$host: $svc не активен — перезапуск"
        add_issue "$host: $svc перезапущен"
        ssh $opts "${user}@${host}" "sudo systemctl restart $svc 2>/dev/null" && log "  OK: $svc" || add_issue "ОШИБКА: $host $svc"
      fi
    fi
  done
}

# Уведомление в Telegram
send_telegram() {
  local msg="$1"
  [[ -z "$NOTIFICATION_BOT_TOKEN" ]] && return 0
  [[ -z "$NOTIFICATION_CHAT_ID" ]] && return 0
  echo "$msg" | curl -s -X POST "https://api.telegram.org/bot${NOTIFICATION_BOT_TOKEN}/sendMessage" \
    -d "chat_id=$NOTIFICATION_CHAT_ID" -d "disable_web_page_preview=true" --data-urlencode "text@-" >/dev/null 2>&1 || true
}

# === MAIN LOOP ===
log "Recovery Watchdog запущен (интервал ${INTERVAL}s)"
mkdir -p "$BACKUPS_ROOT"
LAST_BACKUP=$(date +%s)
BACKUP_INTERVAL=86400  # раз в сутки

while true; do
  NOW=$(date +%s)
  if [[ $((NOW - LAST_BACKUP)) -ge $BACKUP_INTERVAL ]]; then
    for h in server client1 client2; do
      "$SCRIPT_DIR/backup.sh" "$h" 2>/dev/null || true
    done
    LAST_BACKUP=$NOW
    log "Периодический бэкап выполнен"
  fi
  ISSUES=()
  FAILED_HOST=""

  # 1. Проверка server (локально)
  if ! docker info &>/dev/null; then
    log "Сервер: Docker недоступен"
    add_issue "Сервер: Docker недоступен"
    FAILED_HOST="server"
  fi

  # 2. Проверка client1
  if [[ -z "$FAILED_HOST" ]]; then
    if ! check_ping 10.20.0.41; then
      log "client1: недоступен (ping)"
      add_issue "client1 (10.20.0.41): машина не отвечает"
      FAILED_HOST="client1"
    elif ! check_host client1 10.20.0.41; then
      log "client1: SSH недоступен"
      add_issue "client1: SSH недоступен — требуется полное восстановление"
      FAILED_HOST="client1"
    else
      restart_remote_services 10.20.0.41 client1 node_exporter promtail cron
    fi
  fi

  # 3. Проверка client2
  if [[ -z "$FAILED_HOST" ]]; then
    if ! check_ping 10.70.0.41; then
      log "client2: недоступен (ping)"
      add_issue "client2 (10.70.0.41): машина не отвечает"
      FAILED_HOST="client2"
    elif ! check_host client2 10.70.0.41; then
      log "client2: SSH недоступен"
      add_issue "client2: SSH недоступен — требуется полное восстановление"
      FAILED_HOST="client2"
    else
      restart_remote_services 10.70.0.41 client2 node_exporter promtail cron
    fi
  fi

  # 4. При сбое — попытка восстановления (если SSH снова доступен)
  if [[ -n "$FAILED_HOST" ]] && [[ "$FAILED_HOST" != "server" ]]; then
    RHOST=$([[ "$FAILED_HOST" == "client1" ]] && echo "10.20.0.41" || echo "10.70.0.41")
    if check_host "$FAILED_HOST" "$RHOST"; then
      log "Попытка восстановления $FAILED_HOST из бэкапа..."
      if "$SCRIPT_DIR/restore.sh" "$FAILED_HOST" 2>/dev/null; then
        add_issue "$FAILED_HOST: восстановлен из бэкапа"
      fi
    else
      send_telegram "🔴 Recovery: $FAILED_HOST недоступен (SSH/ping). Требуется ручное восстановление из образа. См. docs/RECOVERY.md"
    fi
  fi

  # 5. Отчёт
  if [[ ${#ISSUES[@]} -eq 0 ]]; then
    report="✅ Recovery Watchdog — всё ОК
$(date '+%Y-%m-%d %H:%M')"
  else
    report="⚠️ Recovery Watchdog:
$(printf '%s\n' "${ISSUES[@]}")
$(date '+%Y-%m-%d %H:%M')"
  fi
  send_telegram "$report"

  sleep "$INTERVAL"
done
