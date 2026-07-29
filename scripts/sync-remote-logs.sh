#!/bin/bash
# Копирование логов с nctk и vm1 на campus-server (pull вместо push)
# Клиенты не имеют доступа к campus-server, поэтому campus-server сам забирает логи
# Запуск: на 10.10.4.120, cron каждую минуту или systemd timer

DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_LOGS="$DIR/remote-logs"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

mkdir -p "$REMOTE_LOGS/nctk" "$REMOTE_LOGS/vm1"

sync_host() {
    local user="$1"
    local host="$2"
    local dest="$3"
    rsync -az -e "ssh $SSH_OPTS" \
        --include='*/' --include='*.log' --include='syslog' --include='messages' --include='auth.log' --include='daemon.log' \
        --exclude='*' \
        "$user@$host:/var/log/" \
        "$dest/" \
        2>/dev/null || true
}

sync_host "nctk" "10.20.0.41" "$REMOTE_LOGS/nctk"
sync_host "vm1"  "10.70.0.41" "$REMOTE_LOGS/vm1"
