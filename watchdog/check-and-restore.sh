#!/bin/bash
# Watchdog: проверяет и восстанавливает сервисы. Отправляет отчёт в Telegram после каждой проверки.

SSH_KEY="${SSH_KEY:-/root/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes"
INTERVAL="${CHECK_INTERVAL:-300}"
ISSUES=()

load_notification_config() {
    NOTIFICATION_BOT_TOKEN="${NOTIFICATION_BOT_TOKEN:-}"
    NOTIFICATION_CHAT_ID="${NOTIFICATION_CHAT_ID:-}"
    NOTIFICATION_CHAT_IDS="${NOTIFICATION_CHAT_IDS:-}"
    if [[ -z "$NOTIFICATION_BOT_TOKEN" ]] && [[ -f /app/notification.env ]]; then
        while IFS= read -r line; do
            [[ "$line" =~ ^#.*$ ]] && continue
            [[ "$line" =~ ^BOT_TOKEN=(.+)$ ]] && NOTIFICATION_BOT_TOKEN="${BASH_REMATCH[1]// /}"
            [[ "$line" =~ ^LOG_GROUP_ID=(.+)$ ]] && NOTIFICATION_CHAT_ID="${BASH_REMATCH[1]// /}"
            [[ "$line" =~ ^LOG_GROUP_IDS=(.+)$ ]] && NOTIFICATION_CHAT_IDS="${BASH_REMATCH[1]// /}"
        done < /app/notification.env 2>/dev/null
    fi
}

mask_token() {
    local t="$1"
    [[ -z "$t" ]] && echo "(не задан)" && return
    echo "${t:0:4}***${t: -4}"
}

log() {
    local msg="$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg"
}

add_issue() { ISSUES+=("$1"); }

restart_docker_container() {
    local name="$1"
    [[ -z "$name" ]] && return 0
    [[ "$name" == "campus-watchdog" ]] && return 0
    local status
    status=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null) || return 0
    if [[ "$status" != "running" ]]; then
        log "Сервер: $name не running ($status) — перезапуск"
        add_issue "Сервер: $name был $status, перезапущен"
        docker start "$name" 2>/dev/null && log "  OK: $name" || { log "  ОШИБКА: $name"; add_issue "ОШИБКА перезапуска: $name"; }
    fi
}

restart_remote_systemd() {
    local host="$1" user="$2"
    shift 2
    local services=("$@")
    if ! ssh $SSH_OPTS "${user}@${host}" "true" 2>/dev/null; then
        log "$host: SSH недоступен"
        add_issue "$host: SSH недоступен"
        return
    fi
    for svc in "${services[@]}"; do
        if ssh $SSH_OPTS "${user}@${host}" "systemctl is-enabled $svc 2>/dev/null" &>/dev/null; then
            if ! ssh $SSH_OPTS "${user}@${host}" "systemctl is-active --quiet $svc 2>/dev/null" 2>/dev/null; then
                log "$host: $svc не активен — перезапуск"
                add_issue "$host: $svc перезапущен"
                ssh $SSH_OPTS "${user}@${host}" "sudo systemctl restart $svc 2>/dev/null" && log "  OK: $svc" || add_issue "ОШИБКА: $host $svc"
            fi
        fi
    done
}

restart_remote_docker() {
    local host="$1" user="$2" container="$3"
    if ! ssh $SSH_OPTS "${user}@${host}" "true" 2>/dev/null; then return; fi
    local status=$(ssh $SSH_OPTS "${user}@${host}" "docker inspect -f '{{.State.Status}}' $container 2>/dev/null" || echo "unknown")
    if [[ "$status" != "running" ]] && [[ -n "$status" ]] && [[ "$status" != "unknown" ]]; then
        log "$host: Docker $container не running — перезапуск"
        add_issue "$host: $container перезапущен"
        ssh $SSH_OPTS "${user}@${host}" "docker start $container 2>/dev/null" && log "  OK" || add_issue "ОШИБКА: $host $container"
    fi
}

send_to_telegram() {
    local msg="$1"
    [[ -z "$NOTIFICATION_BOT_TOKEN" ]] && return 0
    local ids=""
    [[ -n "$NOTIFICATION_CHAT_IDS" ]] && ids="$NOTIFICATION_CHAT_IDS" || [[ -n "$NOTIFICATION_CHAT_ID" ]] && ids="$NOTIFICATION_CHAT_ID"
    [[ -z "$ids" ]] && return 0
    local g
    for g in ${ids//,/ }; do
        g="${g// /}"
        [[ -n "$g" ]] && echo "$msg" | curl -s -X POST "https://api.telegram.org/bot${NOTIFICATION_BOT_TOKEN}/sendMessage" \
            -d "chat_id=$g" -d "disable_web_page_preview=true" --data-urlencode "text@-" >/dev/null 2>&1 || true
    done
}

# === MAIN ===
SERVER_CONTAINERS="${SERVER_CONTAINERS:-tg-campus-bot tg-campus-client2 promtail campus-watchdog}"
load_notification_config
log "Watchdog запущен (интервал ${INTERVAL}s, уведомления: $(mask_token "$NOTIFICATION_BOT_TOKEN"))"

while true; do
    ISSUES=()

    for c in $SERVER_CONTAINERS; do
        restart_docker_container "$c"
    done

    restart_remote_systemd "10.20.0.41" "client1" "node_exporter" "promtail" "cron" "crond"
    restart_remote_systemd "10.70.0.41" "client2" "node_exporter" "promtail" "cron" "crond"

    report=""
    if [[ ${#ISSUES[@]} -eq 0 ]]; then
        report="✅ Campus Watchdog — всё ОК
$(date '+%Y-%m-%d %H:%M')"
    else
        report="⚠️ Campus Watchdog — были проблемы:
$(printf '%s\n' "${ISSUES[@]}")
$(date '+%Y-%m-%d %H:%M')"
    fi
    send_to_telegram "$report"

    sleep "$INTERVAL"
done
