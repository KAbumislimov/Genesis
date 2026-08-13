#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  DAILY DIGEST — читает сегодняшний раздел CHANGELOG.md и шлёт в Telegram
#  лично Камрану (или в группу, если личный chat_id не настроен).
#  Запуск: раз в день через cron, см. установку ниже.
#
#  Если за сегодня в CHANGELOG.md ничего не добавлено — ничего не шлёт
#  (не спамит пустыми "сегодня ничего не менялось" сообщениями).
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CHANGELOG="$REPO/../CHANGELOG.md"
TODAY=$(date '+%Y-%m-%d')

[[ -f "$CHANGELOG" ]] || exit 0

SECTION=$(awk -v hdr="## ${TODAY}" '
  $0 == hdr {found=1; next}
  found && /^## / {exit}
  found {print}
' "$CHANGELOG")

# Ничего не добавлено за сегодня — тихо выходим
[[ -n "$(echo "$SECTION" | tr -d '[:space:]')" ]] || exit 0

# Токен/chat_id берём из уже рабочего конфига narimanov-бота (та же
# группа, где Камран реально видит уведомления каждый день)
BOT_ENV="/opt/tg-campus-bot/narimanov.env"
[[ -f "$BOT_ENV" ]] || exit 0
TG_TOKEN=$(grep '^BOT_TOKEN=' "$BOT_ENV" | head -1 | cut -d= -f2-)
TG_CHAT=$(grep '^LOG_GROUP_ID=' "$BOT_ENV" | head -1 | cut -d= -f2-)

[[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]] || exit 0

MSG="📋 Bugünkü dəyişikliklər — ${TODAY}
${SECTION}"

curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT}" \
    --data-urlencode "text=${MSG:0:4000}" \
    -o /dev/null
