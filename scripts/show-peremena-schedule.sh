#!/bin/bash
# Расписание перемен на client1 и client2 (пн–пт)
# Запуск: bash scripts/show-peremena-schedule.sh

SSH="ssh -i ${SSH_KEY:-$HOME/.ssh/campus_bot} -o StrictHostKeyChecking=no -o ConnectTimeout=5"

DAY=$(date +%u)  # 1=пн .. 7=вс
DAYNAME=$(date +%A)
echo "=== Сегодня: $DAYNAME ($(date +%d.%m.%Y)) ==="
echo ""

if [ "$DAY" -eq 6 ] || [ "$DAY" -eq 7 ]; then
  echo "Выходной — перемен нет (cron только пн–пт)"
  exit 0
fi

echo "Папка дня: $DAY (пн=1, вт=2, ср=3, чт=4, пт=5)"
echo ""
echo "┌──────────┬─────────────┬─────────────┐"
echo "│ Время    │ CLIENT1        │ CLIENT2         │"
echo "├──────────┼─────────────┼─────────────┤"
echo "│ 07:45    │ utro        │ utro        │"
echo "│ 07:59    │ stop        │ stop        │"
echo "│ 08:40    │ 1peremena   │ 1peremena   │"
echo "│ 08:45    │ stop        │ stop        │"
echo "│ 09:25    │ 2peremena   │ 2peremena   │"
echo "│ 09:35    │ stop        │ stop        │"
echo "│ 10:15    │ 3peremena   │ 3peremena   │"
echo "│ 10:20    │ stop        │ stop        │"
echo "│ 11:00    │ 4peremena   │ 4peremena   │"
echo "│ 11:05    │ stop        │ stop        │"
echo "│ 11:45    │ 5peremena   │ 5peremena   │"
echo "│ 11:55    │ stop        │ stop        │"
echo "│ 12:35    │ 6peremena   │ 6peremena   │"
echo "│ 12:40    │ stop        │ stop        │"
echo "│ 13:20    │ 7peremena   │ 7peremena   │"
echo "│ 13:30    │ stop        │ stop        │"
echo "│ 14:10    │ 8peremena   │ 8peremena   │"
echo "│ 14:15    │ stop        │ stop        │"
echo "│ 14:55    │ 9peremena   │ 9peremena   │"
echo "│ 15:10    │ stop        │ stop        │"
echo "└──────────┴─────────────┴─────────────┘"
echo ""
echo "Гимн (только понедельник): 08:00 → 08:03 (client1)"
echo ""
echo "Проверка crontab:"
$SSH client1@10.20.0.41 "crontab -l 2>/dev/null | grep -E 'campus-cron|peremena' | head -5" 2>/dev/null || echo "client1: недоступен"
$SSH client2@10.70.0.41 "crontab -l 2>/dev/null | grep -E 'campus-cron|peremena' | head -5" 2>/dev/null || echo "client2: недоступен"
