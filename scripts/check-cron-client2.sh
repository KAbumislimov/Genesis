#!/bin/bash
# Проверка работы крона перемен для client2@10.70.0.41
# Запуск: ./check-cron-client2.sh

LOG="${CRON_MEDIA_LOG:-/home/kamran/campus-infra/cron-media.log}"
CLIENT2_ENV="${CLIENT2_ENV:-/home/kamran/client2.env}"

echo "=== 1. Файл client2.env ==="
[ -r "$CLIENT2_ENV" ] && echo "OK: $CLIENT2_ENV" || echo "ОШИБКА: нет $CLIENT2_ENV"

echo ""
echo "=== 2. Последние записи для client2 в логе (PLAY/SCP fail) ==="
grep -E "client2@10.70.0.41|client2\.env" "$LOG" 2>/dev/null | tail -15

echo ""
echo "=== 3. Ручной тест слота 1peremena на client2 ==="
echo "Выполняю: ENV_FILE=$CLIENT2_ENV /home/kamran/bin/campus-cron-media.sh 1peremena"
HOME=/home/kamran ENV_FILE="$CLIENT2_ENV" /home/kamran/bin/campus-cron-media.sh 1peremena && echo "Тест завершён (код 0)" || echo "Тест завершён с ошибкой (код $?)"
echo ""
echo "Последняя строка лога:"
tail -1 "$LOG"

echo ""
echo "=== 4. Crontab (записи campus-cron для client2) ==="
crontab -l 2>/dev/null | grep -E "CLIENT2_ENV|client2\.env|campus-cron-media" | head -5 || echo "(запустите от пользователя kamran: crontab -l)"
