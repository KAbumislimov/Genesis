#!/bin/bash
# Отключить sync-remote-logs из cron (логи теперь идут через Promtail на клиентах)
# Запуск: на машине, где настроен cron (nctk или campus-server)

echo "Текущий crontab:"
crontab -l 2>/dev/null || echo "(пусто)"

if crontab -l 2>/dev/null | grep -q "sync-remote-logs"; then
    echo ""
    echo "Удаляю sync-remote-logs из cron..."
    crontab -l 2>/dev/null | grep -v "sync-remote-logs" | crontab -
    echo "Готово."
else
    echo "sync-remote-logs не найден в cron."
fi
