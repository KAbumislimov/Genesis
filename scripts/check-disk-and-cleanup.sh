#!/bin/bash
# Анализ диска CentOS и рекомендации по очистке
# Запуск: bash scripts/check-disk-and-cleanup.sh

echo "=== Использование дисков ==="
df -h /

echo ""
echo "=== Крупные каталоги в /home/kamran ==="
du -sh /home/kamran/campus-infra/* /home/kamran/.cursor* 2>/dev/null | sort -hr | head -20

echo ""
echo "=== Docker ==="
docker system df 2>/dev/null || echo "(Docker не доступен)"

echo ""
echo "=== Что можно удалить ==="
echo ""
echo "1. remote-logs (логи client1/client2 — теперь идут через Promtail)"
SIZE_RL=$(du -sh /home/kamran/campus-infra/remote-logs 2>/dev/null | cut -f1)
echo "   Размер: $SIZE_RL"
echo "   Удалить: rm -rf /home/kamran/campus-infra/remote-logs"
echo ""
echo "2. /tmp/campus-monitoring-cache (бинарники deploy — ~100MB)"
SIZE_CACHE=$(du -sh /tmp/campus-monitoring-cache 2>/dev/null | cut -f1 || echo "0")
echo "   Размер: $SIZE_CACHE"
echo "   Удалить: rm -rf /tmp/campus-monitoring-cache"
echo ""
echo "3. Docker: неиспользуемые образы и build cache"
echo "   Удалить: docker system prune -a -f"
echo "   (осторожно: удалит все неиспользуемые образы)"
echo ""
echo "4. Docker: только build cache (безопаснее)"
echo "   Удалить: docker builder prune -f"
echo ""
echo "5. journalctl (логи systemd)"
echo "   Очистить: sudo journalctl --vacuum-time=7d"
echo ""
