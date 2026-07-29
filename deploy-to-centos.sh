#!/bin/bash
# Деплой campus-infra на CentOS (10.10.4.120)
# Запускать с client2. Требует пароль kamran или SSH-ключ.

CENTOS="kamran@10.10.4.120"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Копирование campus-infra на CentOS ==="
scp -r "$DIR" "$CENTOS:/home/kamran/"

echo ""
echo "=== Перезапуск бота на CentOS ==="
ssh "$CENTOS" "cd /home/kamran/campus-infra && docker compose --profile bot down && docker compose --profile bot up -d"

echo ""
echo "=== Логи бота ==="
ssh "$CENTOS" "docker logs tg-campus-bot 2>&1 | tail -20"
