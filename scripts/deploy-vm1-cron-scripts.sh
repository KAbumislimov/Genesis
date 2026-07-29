#!/bin/bash
# Копирование cron-скриптов на vm1 (через jump 10.10.4.120).
# Запуск с машины, где есть доступ к jump.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JUMP="${JUMP_HOST:-10.10.4.120}"
VM1="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"

echo "=== Деплой cron-скриптов на vm1 ($VM1) ==="
scp -o ProxyJump="$JUMP" \
  "$SCRIPT_DIR/campus-cron-landau-local.sh" \
  "$SCRIPT_DIR/campus-cron-stop-local.sh" \
  "$SCRIPT_DIR/vm1-music-debug.sh" \
  "$SCRIPT_DIR/vm1-music-verify.sh" \
  "$SCRIPT_DIR/fix-vm1-campus-mpv-user-service.sh" \
  "$VM1_USER@$VM1:/home/$VM1_USER/"

echo ""
echo "Готово. На vm1 выполните:"
echo "  chmod +x /home/vm1/campus-cron-*.sh"
echo "  sudo apt-get install -y socat   # для корректной остановки (IPC вместо kill -9)"
