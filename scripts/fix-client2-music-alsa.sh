#!/bin/bash
# Исправление: музыка не играет на client2 из-за --audio-device (ALSA device not found).
# Причина: mpv принудительно использует устройство (например USB), которого нет.
# Решение: убрать --audio-device из campus-mpv.service, чтобы mpv использовал default.
#
# Запуск с сервера 10.10.4.120:  bash campus-infra/scripts/fix-client2-music-alsa.sh
# Или с локальной машины через jump:  CLIENT2_JUMP=user@10.10.4.120 bash fix-client2-music-alsa.sh
set -e
CLIENT2_HOST="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Если доступ только через jump-сервер
if [ -n "${CLIENT2_JUMP:-}" ]; then
  SSH_OPTS="$SSH_OPTS -o ProxyJump=$CLIENT2_JUMP"
fi

echo "=== Исправление campus-mpv на client2 (убрать --audio-device) ==="
echo "Подключение: ${CLIENT2_USER}@${CLIENT2_HOST}"
echo ""

# 1. Показать текущий unit
echo "--- Текущий campus-mpv.service ---"
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "sudo cat /etc/systemd/system/campus-mpv.service 2>/dev/null || cat /etc/systemd/system/campus-mpv.service 2>/dev/null" || {
  echo "Ошибка: не удалось прочитать unit. Проверьте SSH."
  exit 1
}
echo ""

# 2. Применить исправление (убрать --audio-device из unit и override)
echo "--- Применение исправления ---"
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" 'bash -s' << 'REMOTE'
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
echo "Готово. Проверьте на client2: при следующей перемене музыка должна играть."
echo "Если нет — смотрите: journalctl -u campus-mpv -f"
echo ""
echo "Ручной вариант (если скрипт не сработал):"
echo "  ssh client2@10.70.0.41"
echo "  sudo sed -i 's/ *--audio-device=[^ ]* *//g' /etc/systemd/system/campus-mpv.service.d/audio.conf"
echo "  sudo systemctl daemon-reload && sudo systemctl restart campus-mpv"
