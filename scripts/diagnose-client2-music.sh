#!/bin/bash
# Диагностика: почему не играет музыка на переменах на client2 (Клиент 2).
# Запуск: с сервера  bash campus-infra/scripts/diagnose-client2-music.sh
#     или на client2:    bash diagnose-client2-music.sh  (предварительно скопировать)
set -e
CLIENT2_HOST="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"
CLIENT2_HOME="/home/$CLIENT2_USER"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

run_remote() {
  if [ -n "${ON_CLIENT2:-}" ]; then
    bash -c "$1"
  else
    ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "$1"
  fi
}

echo "=== 1. Лог action.log (последние 30 строк) ==="
run_remote "tail -30 ${CLIENT2_HOME}/action.log 2>/dev/null || echo 'Файл пуст или нет'" 2>/dev/null || echo "(SSH недоступен — запустите скрипт на client2: ON_CLIENT2=1 bash $0)"

echo ""
echo "=== 2. Служба cron ==="
run_remote "systemctl is-active cron 2>/dev/null || systemctl is-active crond 2>/dev/null; which crontab" 2>/dev/null || true

echo ""
echo "=== 3. Записи crontab (campus) ==="
run_remote "crontab -l 2>/dev/null | grep -E 'campus-cron|Media'" 2>/dev/null || true

echo ""
echo "=== 4. Папка Media и файлы на сегодня (день $(date +%u)) ==="
run_remote "DAY=\$(date +%u); echo \"День недели: \$DAY\"; ls -la ${CLIENT2_HOME}/Media/\$DAY/*.mp3 2>/dev/null | head -8 || echo 'Нет mp3 в Media/\$DAY'" 2>/dev/null || true

echo ""
echo "=== 5. campus-mpv.service (звук перемен) ==="
run_remote "systemctl is-active campus-mpv 2>/dev/null; systemctl status campus-mpv --no-pager 2>/dev/null | head -15; echo '---'; grep -E 'ExecStart|audio-device' /etc/systemd/system/campus-mpv.service 2>/dev/null || true" 2>/dev/null || true

echo ""
echo "=== 6. Последние ошибки mpv (ALSA) ==="
run_remote "journalctl -u campus-mpv -n 20 --no-pager 2>/dev/null | grep -E 'alsa|audio|Audio|error|Error' || echo 'нет записей'" 2>/dev/null || true

echo ""
echo "=== 7. Права inbox и campus-playerctl ==="
run_remote "ls -la /var/lib/campus-player/inbox 2>/dev/null; which campus-playerctl; /usr/local/bin/campus-playerctl status 2>&1" 2>/dev/null || true

echo ""
echo "=== 8. Ручной запуск слота 1peremena ==="
run_remote "MEDIA_ROOT=${CLIENT2_HOME}/Media LOG_FILE=${CLIENT2_HOME}/action.log ${CLIENT2_HOME}/campus-cron-media-local.sh 1peremena 115 2>&1; echo \"Exit: \$?\"" 2>/dev/null || true

echo ""
echo "=== 9. action.log после теста ==="
run_remote "tail -8 ${CLIENT2_HOME}/action.log 2>/dev/null" 2>/dev/null || true

echo ""
echo "--- Типичные причины, если музыка не играет ---"
echo "• ALSA: [ao/alsa] Playback open error / --audio-device — устройство не найдено."
echo "  Решение: bash campus-infra/scripts/fix-client2-music-alsa.sh (убирает --audio-device)"
echo "• Нет звука при запуске из cron: у cron нет доступа к DISPLAY и PulseAudio."
echo "  Решение: пользователь client2 должен быть залогинен в графическую сессию (автологин)."
echo "• mpv не запущен: при первом play campus-playerctl запускает mpv. Если сессии нет — звука не будет."
echo "• Нет файлов в Media/N: с сервера: bash campus-infra/scripts/install-crontab-media-local-client2.sh"
echo "• В логе ❌: смотреть action.log — «нет файла» или ошибка play."
