#!/bin/bash
# Запускать **на vm1** (vm1@10.70.0.41). Проверяет плеер и inbox локально.
# На сервер скопировать и выполнить: scp ... vm1:~/check-player-on-vm1.sh && ssh vm1 'bash ~/check-player-on-vm1.sh'

echo "=== Inbox ==="
ls -la /var/lib/campus-player/inbox/ 2>/dev/null || echo "Нет доступа к inbox"
echo ""
echo "=== campus-playerctl ==="
/usr/local/bin/campus-playerctl status 2>/dev/null || echo "campus-playerctl не найден или ошибка"
echo ""
echo "Проверка лога и крона — на СЕРВЕРЕ: tail -30 /home/kamran/campus-infra/cron-landau.log"
