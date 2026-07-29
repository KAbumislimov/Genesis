#!/bin/bash
# Восстановление client1 (Клиент 1) — Cockpit + настройки
# Запускать с CentOS: bash scripts/restore-client1.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a
CLIENT1_HOST="10.20.0.41"
CLIENT1_USER="client1"
CLIENT1_PASS="${CLIENT1_PASS:?Укажите пароль: CLIENT1_PASS=... bash scripts/restore-client1.sh (или добавьте в .env)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"

ssh_client1() { sshpass -p "$CLIENT1_PASS" ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${CLIENT1_USER}@${CLIENT1_HOST}" "$@"; }

echo "[client1] Проверяю Cockpit..."
ssh_client1 "echo '$CLIENT1_PASS' | sudo -S bash -c '
  systemctl enable cockpit.socket
  systemctl restart cockpit.socket cockpit 2>/dev/null || true
  systemctl is-active cockpit && echo OK || echo FAIL
'"

echo "[client1] Готово. Cockpit доступен: http://10.20.0.41:1991"
echo "       Логин: client1 / (см. campus-secrets)"
