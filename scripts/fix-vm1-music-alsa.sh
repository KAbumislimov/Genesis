#!/bin/bash
# Исправление: музыка не играет на vm1 из-за --audio-device (ALSA device not found).
# Причина: mpv принудительно использует устройство (например USB), которого нет.
# Решение: убрать --audio-device из campus-mpv.service, чтобы mpv использовал default.
#
# Запуск с сервера 10.10.4.120:  bash campus-infra/scripts/fix-vm1-music-alsa.sh
# Или с локальной машины через jump:  VM1_JUMP=user@10.10.4.120 bash fix-vm1-music-alsa.sh
set -e
VM1_HOST="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Если доступ только через jump-сервер
if [ -n "${VM1_JUMP:-}" ]; then
  SSH_OPTS="$SSH_OPTS -o ProxyJump=$VM1_JUMP"
fi

echo "=== Исправление campus-mpv на vm1 (убрать --audio-device) ==="
echo "Подключение: ${VM1_USER}@${VM1_HOST}"
echo ""

# 1. Показать текущий unit
echo "--- Текущий campus-mpv.service ---"
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "sudo cat /etc/systemd/system/campus-mpv.service 2>/dev/null || cat /etc/systemd/system/campus-mpv.service 2>/dev/null" || {
  echo "Ошибка: не удалось прочитать unit. Проверьте SSH."
  exit 1
}
echo ""

# 2. Применить исправление (убрать --audio-device из unit и override)
echo "--- Применение исправления ---"
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" 'bash -s' << 'REMOTE'
set -e
SVC="/etc/systemd/system/campus-mpv.service"
OVERRIDE_DIR="/etc/systemd/system/campus-mpv.service.d"

# Бэкап и исправление основного unit
if [ -f "$SVC" ]; then
  sudo cp "$SVC" "${SVC}.bak.$(date +%Y%m%d%H%M%S)"
  sudo sed -i 's/ *--audio-device=[^ ]* *//g' "$SVC"
fi

# Исправление override (audio.conf и др.)
for f in "$OVERRIDE_DIR"/*.conf; do
  [ -f "$f" ] || continue
  sudo sed -i 's/ *--audio-device=[^ ]* *//g' "$f"
done

echo "Исправление применено. Перезагрузка сервиса..."
sudo systemctl daemon-reload
sudo systemctl restart campus-mpv
sleep 2
sudo systemctl status campus-mpv --no-pager || true
REMOTE

echo ""
echo "Готово. Проверьте на vm1: при следующей перемене музыка должна играть."
echo "Если нет — смотрите: journalctl -u campus-mpv -f"
echo ""
echo "Ручной вариант (если скрипт не сработал):"
echo "  ssh vm1@10.70.0.41"
echo "  sudo sed -i 's/ *--audio-device=[^ ]* *//g' /etc/systemd/system/campus-mpv.service.d/audio.conf"
echo "  sudo systemctl daemon-reload && sudo systemctl restart campus-mpv"
