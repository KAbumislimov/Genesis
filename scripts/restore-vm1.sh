#!/bin/bash
# Восстановление vm1 (Гянджлик) — Cockpit + настройки
# Запускать с CentOS: bash scripts/restore-vm1.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a
VM1_HOST="10.70.0.41"
VM1_USER="vm1"
VM1_PASS="${VM1_PASS:?Укажите пароль: VM1_PASS=... bash scripts/restore-vm1.sh (или добавьте в .env)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"

ssh_vm1() { sshpass -p "$VM1_PASS" ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${VM1_USER}@${VM1_HOST}" "$@"; }
scp_vm1() { sshpass -p "$VM1_PASS" scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$@"; }

echo "[vm1] Копирую конфиги Cockpit..."
scp_vm1 "$REPO/config/cockpit-vm1/cockpit.conf" "${VM1_USER}@${VM1_HOST}:/tmp/cockpit.conf"
scp_vm1 "$REPO/config/cockpit-vm1/cockpit-socket-override.conf" "${VM1_USER}@${VM1_HOST}:/tmp/cockpit-override.conf"

ssh_vm1 "echo '$VM1_PASS' | sudo -S bash -c '
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

echo "[vm1] Готово. Cockpit доступен через: http://10.10.4.120:19912"
echo "       Логин: vm1 / (см. campus-secrets)"
