#!/bin/bash
# Восстановление client2 (Клиент 2) — Cockpit + настройки
# Запускать с CentOS: bash scripts/restore-client2.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a
CLIENT2_HOST="10.70.0.41"
CLIENT2_USER="client2"
CLIENT2_PASS="${CLIENT2_PASS:?Укажите пароль: CLIENT2_PASS=... bash scripts/restore-client2.sh (или добавьте в .env)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"

ssh_client2() { sshpass -p "$CLIENT2_PASS" ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${CLIENT2_USER}@${CLIENT2_HOST}" "$@"; }
scp_client2() { sshpass -p "$CLIENT2_PASS" scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$@"; }

echo "[client2] Копирую конфиги Cockpit..."
scp_client2 "$REPO/config/cockpit-client2/cockpit.conf" "${CLIENT2_USER}@${CLIENT2_HOST}:/tmp/cockpit.conf"
scp_client2 "$REPO/config/cockpit-client2/cockpit-socket-override.conf" "${CLIENT2_USER}@${CLIENT2_HOST}:/tmp/cockpit-override.conf"

ssh_client2 "echo '$CLIENT2_PASS' | sudo -S bash -c '
  mkdir -p /etc/cockpit /etc/systemd/system/cockpit.socket.d
  cp /tmp/cockpit.conf /etc/cockpit/cockpit.conf
  cp /tmp/cockpit-override.conf /etc/systemd/system/cockpit.socket.d/override.conf
  # Убрать TLS если остался
  [ -f /etc/cockpit/ws-certs.d/0-self-signed.cert ] && mv /etc/cockpit/ws-certs.d/0-self-signed.cert /etc/cockpit/ws-certs.d/0-self-signed.cert.disabled 2>/dev/null || true
  [ -f /etc/cockpit/ws-certs.d/0-self-signed.key ]  && mv /etc/cockpit/ws-certs.d/0-self-signed.key  /etc/cockpit/ws-certs.d/0-self-signed.key.disabled  2>/dev/null || true
  systemctl daemon-reload
  systemctl enable cockpit.socket
  systemctl restart cockpit.socket cockpit
  systemctl is-active cockpit && echo OK
'"

echo "[client2] Готово. Cockpit доступен через: http://10.10.4.120:19912"
echo "       Логин: client2 / (см. campus-secrets)"
