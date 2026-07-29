#!/bin/bash
# Запускать **на client2** (client2@10.70.0.41). Проверяет плеер и inbox локально.
# На сервер скопировать и выполнить: scp ... client2:~/check-player-on-client2.sh && ssh client2 'bash ~/check-player-on-client2.sh'

echo "=== Inbox ==="
ls -la /var/lib/campus-player/inbox/ 2>/dev/null || echo "Нет доступа к inbox"
echo ""
echo "=== campus-playerctl ==="
/usr/local/bin/campus-playerctl status 2>/dev/null || echo "campus-playerctl не найден или ошибка"
echo ""
echo "Проверка лога и крона — на СЕРВЕРЕ: tail -30 /home/kamran/campus-infra/cron-media.log"
