#!/bin/bash
# Освобождение места на диске — сервер заполнен (no space left on device)
# Запуск: cd /home/kamran/campus-infra && bash scripts/free-disk-space.sh

set -e

echo "=== Использование диска ==="
df -h / /tmp 2>/dev/null || df -h

echo ""
echo "=== Топ Docker volumes ==="
sudo du -sh /var/lib/docker/volumes/* 2>/dev/null | sort -hr | head -15

echo ""
echo "=== Топ Docker overlay ==="
sudo du -sh /var/lib/docker/overlay2/* 2>/dev/null | sort -hr | head -10

echo ""
echo "=== Размер /tmp ==="
du -sh /tmp 2>/dev/null

echo ""
echo "=== Рекомендуемые действия ==="
echo "1. Очистить неиспользуемые Docker-данные:"
echo "   docker system prune -a -f --volumes"
echo "   (Удалит неиспользуемые образы, контейнеры и volumes!)"
echo ""
echo "2. Только образы и контейнеры (без volumes):"
echo "   docker system prune -a -f"
echo ""
echo "3. Удалить старые логи журнала:"
echo "   sudo journalctl --vacuum-size=100M"
echo ""
echo "4. Поиск крупных файлов:"
echo "   sudo du -ah /var/lib/docker 2>/dev/null | sort -rh | head -20"
