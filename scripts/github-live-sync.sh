#!/bin/bash
# github-live-sync: постоянно (poll каждые 45с, без root/inotify) проверяет
# campus-infra + helpdesk-ops + ops-journal на изменения и, если есть что-то
# новое, сразу коммитит и пушит в GitHub (не ждёт часовой крон) — и шлёт
# Telegram-уведомление о том, что именно уехало. Полностью на сервере,
# не зависит от компьютера Камрана.
#
# Запуск/остановка — через github-live-sync-watchdog.sh (следит, чтобы этот
# процесс всегда был жив, перезапускает при падении/перезагрузке сервера).
set -uo pipefail

REPO_DIR="$HOME/projects"
INFRA_DIR="$REPO_DIR/campus-infra"
LOG="$HOME/log/github-live-sync.log"
BOT_ENV="/opt/tg-campus-bot/narimanov.env"
POLL_INTERVAL=45

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify_telegram() {
    local sha="$1" stat msg tok chat
    [[ -f "$BOT_ENV" ]] || return 0
    tok=$(grep '^BOT_TOKEN=' "$BOT_ENV" | head -1 | cut -d= -f2-)
    chat=$(grep '^LOG_GROUP_ID=' "$BOT_ENV" | head -1 | cut -d= -f2-)
    [[ -n "$tok" && -n "$chat" ]] || return 0
    stat=$(git -C "$REPO_DIR" show --stat --format='' "$sha" 2>/dev/null | head -n 12)
    msg="💾 Auto-sync GitHub — yeni dəyişikliklər push edildi ($(date '+%Y-%m-%d %H:%M'))
${stat}"
    curl -s -X POST "https://api.telegram.org/bot${tok}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=${msg:0:3500}" -o /dev/null
}

log "github-live-sync запущен (poll ${POLL_INTERVAL}s, pid $$)"
while true; do
    before=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "")
    bash "$INFRA_DIR/scripts/backup-to-github.sh" >> "$LOG" 2>&1
    after=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "")
    if [[ -n "$after" && "$after" != "$before" ]]; then
        log "Новый коммит $after — шлю уведомление"
        notify_telegram "$after"
    fi
    sleep "$POLL_INTERVAL"
done
