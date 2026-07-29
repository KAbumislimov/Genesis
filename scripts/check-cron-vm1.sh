#!/bin/bash
# Проверка работы крона перемен для vm1@10.70.0.41
# Запуск: ./check-cron-vm1.sh

LOG="${CRON_LANDAU_LOG:-/home/kamran/campus-infra/cron-landau.log}"
VM1_ENV="${VM1_ENV:-/home/kamran/vm1.env}"

echo "=== 1. Файл vm1.env ==="
[ -r "$VM1_ENV" ] && echo "OK: $VM1_ENV" || echo "ОШИБКА: нет $VM1_ENV"

echo ""
echo "=== 2. Последние записи для vm1 в логе (PLAY/SCP fail) ==="
grep -E "vm1@10.70.0.41|vm1\.env" "$LOG" 2>/dev/null | tail -15

echo ""
echo "=== 3. Ручной тест слота 1peremena на vm1 ==="
echo "Выполняю: ENV_FILE=$VM1_ENV /home/kamran/bin/campus-cron-landau.sh 1peremena"
HOME=/home/kamran ENV_FILE="$VM1_ENV" /home/kamran/bin/campus-cron-landau.sh 1peremena && echo "Тест завершён (код 0)" || echo "Тест завершён с ошибкой (код $?)"
echo ""
echo "Последняя строка лога:"
tail -1 "$LOG"

echo ""
echo "=== 4. Crontab (записи campus-cron для vm1) ==="
crontab -l 2>/dev/null | grep -E "VM1_ENV|vm1\.env|campus-cron-landau" | head -5 || echo "(запустите от пользователя kamran: crontab -l)"
