#!/bin/bash
# Меняет CLIENT_HOST в env-файле серверного control-бота кампуса (кнопки
# Громче/Тише/Стоп в Telegram) и перезапускает его. Кампус и пути берутся
# ТОЛЬКО из config/campus-bots.conf — скрипт не может тронуть произвольный
# файл, поэтому его можно безопасно разрешить через NOPASSWD sudo (см.
# docs/ROLES-PERMISSIONS.md → «Серверный control-бот»).
#
# Запуск: sudo campus-bot-sethost.sh <кампус> <новый_ip>
#   sudo campus-bot-sethost.sh cgtk 10.50.0.41
set -euo pipefail
CONF="$(cd "$(dirname "$0")/.." && pwd)/config/campus-bots.conf"
CAMPUS="${1:-}"; NEW_IP="${2:-}"

if [[ -z "$CAMPUS" || -z "$NEW_IP" ]]; then
    echo "Использование: $0 <кампус> <новый_ip>" >&2
    exit 1
fi
if [[ ! "$NEW_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "«$NEW_IP» не похоже на IP-адрес" >&2
    exit 1
fi

LINE="$(grep -m1 "^${CAMPUS}:" "$CONF" || true)"
if [[ -z "$LINE" ]]; then
    echo "Кампус «$CAMPUS» не найден в $CONF — control-бот для него не зарегистрирован" >&2
    exit 1
fi
IFS=':' read -r _ SERVICE ENV_FILE <<<"$LINE"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Нет файла $ENV_FILE" >&2
    exit 1
fi

sed -i "s/^CLIENT_HOST=.*/CLIENT_HOST=${NEW_IP}/" "$ENV_FILE"
systemctl restart "$SERVICE"
echo "✅ $CAMPUS: CLIENT_HOST=$NEW_IP, $SERVICE перезапущен"
