#!/bin/bash
# Восстановление nctk (Нариманов) — Cockpit + настройки
# Запускать с CentOS: bash scripts/restore-nctk.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a
NCTK_HOST="10.20.0.41"
NCTK_USER="nctk"
NCTK_PASS="${NCTK_PASS:?Укажите пароль: NCTK_PASS=... bash scripts/restore-nctk.sh (или добавьте в .env)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"

ssh_nctk() { sshpass -p "$NCTK_PASS" ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${NCTK_USER}@${NCTK_HOST}" "$@"; }

echo "[nctk] Проверяю Cockpit..."
ssh_nctk "echo '$NCTK_PASS' | sudo -S bash -c '
  systemctl enable cockpit.socket
  systemctl restart cockpit.socket cockpit 2>/dev/null || true
  systemctl is-active cockpit && echo OK || echo FAIL
'"

echo "[nctk] Готово. Cockpit доступен: http://10.20.0.41:1991"
echo "       Логин: nctk / (см. campus-secrets)"
