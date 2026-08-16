#!/bin/bash
# Уведомление в Telegram при SSH-входе на машину.
# Устанавливается в /etc/profile.d/campus-notify-login.sh
# Срабатывает при каждом интерактивном SSH-логине.

[[ -z "$SSH_CLIENT" && -z "$SSH_CONNECTION" ]] && return 0

ENV_FILE="${HOME}/cron_notify.env"
[[ ! -f "$ENV_FILE" ]] && ENV_FILE="/home/cgtk/cron_notify.env"
[[ ! -f "$ENV_FILE" ]] && return 0

BOT_TOKEN=$(grep '^BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')
LOG_GROUP_ID=$(grep '^LOG_GROUP_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '[:space:]')

[[ -z "$BOT_TOKEN" || -z "$LOG_GROUP_ID" ]] && return 0

HOSTNAME=$(hostname -s)
WHO=$(whoami)
CLIENT_IP=$(echo "$SSH_CLIENT" | awk '{print $1}')
LOGIN_TIME=$(date '+%Y-%m-%d %H:%M:%S')
TTY=$(tty 2>/dev/null | sed 's|/dev/||')

MSG="🔑 SSH LOGIN — ${HOSTNAME}
👤 Пользователь: ${WHO}
🌐 IP клиента: ${CLIENT_IP}
⏰ Время: ${LOGIN_TIME}
🖥 TTY: ${TTY}"

curl -s --max-time 8 \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LOG_GROUP_ID}&text=${MSG}" \
    > /dev/null 2>&1 &

return 0
