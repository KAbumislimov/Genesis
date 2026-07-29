#!/bin/bash
# Копирование cron-скриптов на client2 (через jump 10.10.4.120).
# Запуск с машины, где есть доступ к jump.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JUMP="${JUMP_HOST:-10.10.4.120}"
CLIENT2="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"

echo "=== Деплой cron-скриптов на client2 ($CLIENT2) ==="
scp -o ProxyJump="$JUMP" \
  "$SCRIPT_DIR/campus-cron-media-local.sh" \
  "$SCRIPT_DIR/campus-cron-stop-local.sh" \
  "$SCRIPT_DIR/client2-music-debug.sh" \
  "$SCRIPT_DIR/client2-music-verify.sh" \
  "$SCRIPT_DIR/fix-client2-campus-mpv-user-service.sh" \
  "$CLIENT2_USER@$CLIENT2:/home/$CLIENT2_USER/"

echo ""
echo "Готово. На client2 выполните:"
echo "  chmod +x /home/client2/campus-cron-*.sh"
echo "  sudo apt-get install -y socat   # для корректной остановки (IPC вместо kill -9)"
