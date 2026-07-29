#!/bin/bash
# Проверка готовности музыки на vm1 — выполнить НА vm1.
# Добавляет тестовый cron на ближайшие 3–4 минуты, проверяет play+stop.
set -e

echo "=== Проверка музыки vm1 ==="

# Текущее время
NOW=$(date +%M)
NOW=$((10#$NOW))
echo "Сейчас: $(date '+%H:%M')"

# Минуты через 2 и 4
M1=$(( (NOW + 2) % 60 ))
M2=$(( (NOW + 4) % 60 ))
H=$(date +%H)

echo ""
echo "1. Сокет mpv:"
[ -S /run/campus-player/mpv.sock ] && echo "   ✅ Есть" || { echo "   ❌ Нет — запустите campus-mpv"; exit 1; }

echo ""
echo "2. Файлы Landau (пятница=папка 5):"
for f in 1peremena 6peremena; do
  [ -f /home/vm1/Landau/5/${f}.mp3 ] && echo "   ✅ $f.mp3" || echo "   ❌ $f.mp3"
done

echo ""
echo "3. Скрипты:"
[ -x /home/vm1/campus-cron-landau-local.sh ] && echo "   ✅ campus-cron-landau-local.sh" || echo "   ❌ campus-cron-landau-local.sh"
[ -x /home/vm1/campus-cron-stop-local.sh ] && echo "   ✅ campus-cron-stop-local.sh" || echo "   ❌ campus-cron-stop-local.sh"

echo ""
echo "4. socat:"
command -v socat >/dev/null && echo "   ✅ Установлен" || { echo "   ❌ Установите: sudo apt install socat"; exit 1; }

echo ""
echo "5. Тест play + stop:"
LANDAU_ROOT=/home/vm1/Landau LOG_FILE=/home/vm1/action.log /home/vm1/campus-cron-landau-local.sh 1peremena 115
echo "   ▶ Запущено. Слышите звук? (3 сек)"
sleep 3
echo '{"command":["quit"]}' | socat - UNIX-CONNECT:/run/campus-player/mpv.sock 2>/dev/null && echo "   ✅ Остановлено" || echo "   ⚠ Остановка через сокет"

echo ""
echo "=== ТЕСТ ЧЕРЕЗ CRON (опционально) ==="
echo "Чтобы проверить работу по расписанию, добавьте тестовые строки в crontab -e:"
echo ""
printf "   # ТЕСТ — удалить после проверки\n   %d %s * * * LANDAU_ROOT=/home/vm1/Landau LOG_FILE=/home/vm1/action.log /home/vm1/campus-cron-landau-local.sh 1peremena 115\n   %d %s * * * /home/vm1/campus-cron-stop-local.sh\n" $M1 $H $M2 $H
echo ""
echo "Подождите 5 мин → tail -5 /home/vm1/action.log → journalctl -u campus-mpv -n 15"
echo "Нет status=9/KILL = OK. Удалите тестовые строки из crontab."
echo ""
