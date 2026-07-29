#!/bin/bash
# Диагностика: почему не играет музыка на переменах на vm1 (Гянджлик).
# Запуск: с сервера  bash campus-infra/scripts/diagnose-vm1-music.sh
#     или на vm1:    bash diagnose-vm1-music.sh  (предварительно скопировать)
set -e
VM1_HOST="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"
VM1_HOME="/home/$VM1_USER"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

run_remote() {
  if [ -n "${ON_VM1:-}" ]; then
    bash -c "$1"
  else
    ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "$1"
  fi
}

echo "=== 1. Лог action.log (последние 30 строк) ==="
run_remote "tail -30 ${VM1_HOME}/action.log 2>/dev/null || echo 'Файл пуст или нет'" 2>/dev/null || echo "(SSH недоступен — запустите скрипт на vm1: ON_VM1=1 bash $0)"

echo ""
echo "=== 2. Служба cron ==="
run_remote "systemctl is-active cron 2>/dev/null || systemctl is-active crond 2>/dev/null; which crontab" 2>/dev/null || true

echo ""
echo "=== 3. Записи crontab (campus) ==="
run_remote "crontab -l 2>/dev/null | grep -E 'campus-cron|Landau'" 2>/dev/null || true

echo ""
echo "=== 4. Папка Landau и файлы на сегодня (день $(date +%u)) ==="
run_remote "DAY=\$(date +%u); echo \"День недели: \$DAY\"; ls -la ${VM1_HOME}/Landau/\$DAY/*.mp3 2>/dev/null | head -8 || echo 'Нет mp3 в Landau/\$DAY'" 2>/dev/null || true

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
run_remote "LANDAU_ROOT=${VM1_HOME}/Landau LOG_FILE=${VM1_HOME}/action.log ${VM1_HOME}/campus-cron-landau-local.sh 1peremena 115 2>&1; echo \"Exit: \$?\"" 2>/dev/null || true

echo ""
echo "=== 9. action.log после теста ==="
run_remote "tail -8 ${VM1_HOME}/action.log 2>/dev/null" 2>/dev/null || true

echo ""
echo "--- Типичные причины, если музыка не играет ---"
echo "• ALSA: [ao/alsa] Playback open error / --audio-device — устройство не найдено."
echo "  Решение: bash campus-infra/scripts/fix-vm1-music-alsa.sh (убирает --audio-device)"
echo "• Нет звука при запуске из cron: у cron нет доступа к DISPLAY и PulseAudio."
echo "  Решение: пользователь vm1 должен быть залогинен в графическую сессию (автологин)."
echo "• mpv не запущен: при первом play campus-playerctl запускает mpv. Если сессии нет — звука не будет."
echo "• Нет файлов в Landau/N: с сервера: bash campus-infra/scripts/install-crontab-landau-local-vm1.sh"
echo "• В логе ❌: смотреть action.log — «нет файла» или ошибка play."
