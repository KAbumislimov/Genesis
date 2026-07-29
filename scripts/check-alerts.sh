#!/bin/bash
# Disk + service health check → Telegram alerts
# Run from CentOS server (has SSH access to all machines)
# Cron: */5 * * * * /home/kamran/projects/campus-infra/scripts/check-alerts.sh

set -euo pipefail

SSH_KEY="${SSH_KEY:-/home/kamran/.ssh/campus_bot}"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes"

# Load Telegram config from bot_config.env
BOT_TOKEN=""
CHAT_IDS=""
if [ -f /bot_config.env ]; then
    source /bot_config.env 2>/dev/null || true
    BOT_TOKEN="${BOT_TOKEN:-${BOT_TOKEN:-}}"
    CHAT_IDS="${LOG_GROUP_IDS:-${LOG_GROUP_ID:-}}"
fi
# Override from env
BOT_TOKEN="${TG_BOT_TOKEN:-$BOT_TOKEN}"
CHAT_IDS="${TG_LOG_GROUPS:-$CHAT_IDS}"

DISK_THRESHOLD=80
ALERT_COOLDOWN=3600  # seconds between repeated alerts for same issue
STATE_DIR="/tmp/campus-alerts"
mkdir -p "$STATE_DIR"

send_tg() {
    local text="$1"
    [ -z "$BOT_TOKEN" ] && return
    [ -z "$CHAT_IDS" ] && return
    for chat_id in $(echo "$CHAT_IDS" | tr ',' ' '); do
        curl -sS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${chat_id}&text=${text}&parse_mode=HTML" > /dev/null 2>&1 || true
    done
}

alert_if_new() {
    local key="$1"
    local msg="$2"
    local state_file="$STATE_DIR/${key}.last"
    local now
    now=$(date +%s)
    if [ -f "$state_file" ]; then
        local last
        last=$(cat "$state_file")
        if (( now - last < ALERT_COOLDOWN )); then
            return  # already alerted recently
        fi
    fi
    echo "$now" > "$state_file"
    send_tg "$msg"
}

check_machine() {
    local name="$1"
    local host="$2"
    local user="$3"
    local service="$4"

    # Check reachability
    if ! ssh $SSH_OPTS "$user@$host" true 2>/dev/null; then
        alert_if_new "unreachable_${name}" \
            "🔴 <b>Campus Alert</b>%0A⚠️ ${name} недоступен по SSH%0A🖥 ${host}"
        return
    fi

    # Disk check
    local disk_pct
    disk_pct=$(ssh $SSH_OPTS "$user@$host" "df / | awk 'NR==2{print int(\$5)}'" 2>/dev/null || echo 0)
    if (( disk_pct >= DISK_THRESHOLD )); then
        local free
        free=$(ssh $SSH_OPTS "$user@$host" "df -h / | awk 'NR==2{print \$4}'" 2>/dev/null || echo "?")
        alert_if_new "disk_${name}" \
            "💾 <b>Диск почти полон — ${name}</b>%0A📊 Занято: ${disk_pct}%%0AСвободно: ${free}%0A🖥 ${host}"
    else
        rm -f "$STATE_DIR/disk_${name}.last"
    fi

    # Service check
    if [ -n "$service" ]; then
        local status
        status=$(ssh $SSH_OPTS "$user@$host" "systemctl is-active '$service' 2>/dev/null || echo inactive" 2>/dev/null || echo "unreachable")
        if [ "$status" != "active" ]; then
            alert_if_new "svc_${name}_${service}" \
                "🔴 <b>Сервис упал — ${name}</b>%0A⚙️ ${service}: ${status}%0A🖥 ${host}"
        else
            rm -f "$STATE_DIR/svc_${name}_${service}.last"
        fi
    fi
}

# CentOS — check docker
check_machine "CentOS"    "10.10.4.120" "kamran" "docker"
# Narimanov — check campus-player
check_machine "Narimanov" "10.20.0.41"  "nctk"   "campus-player"
# Genclik — check campus-player (uses password auth, skip if no key)
check_machine "Genclik"   "10.70.0.41"  "vm1"    "campus-player"
