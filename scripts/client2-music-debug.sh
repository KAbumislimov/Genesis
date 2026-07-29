#!/bin/bash
# Диагностика музыки на client2 — выполнить НА client2.
echo "=== 1. action.log (последние записи cron) ==="
tail -15 /home/client2/action.log 2>/dev/null || echo "Нет файла"

echo ""
echo "=== 2. journalctl campus-mpv (последние 25 строк) ==="
journalctl -u campus-mpv -n 25 --no-pager 2>/dev/null || journalctl --user -u campus-mpv -n 25 --no-pager 2>/dev/null || echo "Сервис не найден"

echo ""
echo "=== 3. OOM killer (dmesg) ==="
sudo dmesg 2>/dev/null | grep -i "killed process" | tail -5 || echo "Нет записей"

echo ""
echo "=== 4. Сокет mpv ==="
ls -la /run/campus-player/mpv.sock 2>/dev/null || echo "Сокет не найден"

echo ""
echo "=== 5. Файлы 6peremena (пятница=папка 5) ==="
ls -la /home/client2/Media/5/6peremena* 2>/dev/null || echo "Файл не найден"
