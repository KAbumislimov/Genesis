#!/bin/bash
# Полное удаление BT Panel (aaPanel) с CentOS
# Запуск: sudo bash scripts/remove-bt-panel.sh

set -e

echo "=== Удаление BT Panel ==="

# 1. Остановить, отключить и замаскировать supervisord
if systemctl is-active --quiet supervisord 2>/dev/null; then
    echo "Останавливаю supervisord..."
    systemctl stop supervisord
fi
systemctl disable supervisord 2>/dev/null || true
systemctl mask supervisord 2>/dev/null || true
# Удалить unit-файлы во всех возможных местах
rm -f /etc/systemd/system/supervisord.service /usr/lib/systemd/system/supervisord.service 2>/dev/null
rm -rf /etc/systemd/system/supervisord.service.d 2>/dev/null
systemctl daemon-reload 2>/dev/null || true

# 2. Остановить и удалить bt service
if [[ -f /etc/init.d/bt ]]; then
    echo "Останавливаю bt..."
    /etc/init.d/bt stop 2>/dev/null || service bt stop 2>/dev/null || true
    (chkconfig --del bt 2>/dev/null) || (systemctl disable bt 2>/dev/null) || true
    rm -f /etc/init.d/bt
fi

# 3. Удалить команду bt
[[ -f /usr/bin/bt ]] && rm -f /usr/bin/bt && echo "Удалён /usr/bin/bt"

# 4. Удалить панель
if [[ -d /www/server/panel ]]; then
    echo "Удаляю /www/server/panel..."
    rm -rf /www/server/panel
fi

# 5. Удалить site_total (если был от BT)
if systemctl is-enabled site_total.service 2>/dev/null; then
    systemctl stop site_total.service 2>/dev/null || true
    systemctl disable site_total.service 2>/dev/null || true
fi

# 6. Отключить pmlogger_daily (PCP — если не нужен)
for u in pmlogger_daily pmie_daily; do
    systemctl disable $u 2>/dev/null && echo "Отключён $u" || true
    systemctl stop $u 2>/dev/null || true
done

echo ""
echo "Готово. BT Panel удалён."
echo ""
echo "Опционально (если не используете nginx/mysql от BT Panel):"
echo "  rm -rf /www/server   # nginx, mysql, php от BT"
echo "  rm -rf /www/wwwroot  # сайты"
echo "  rm -rf /www/backup   # бэкапы BT"
echo "  rm -rf /www/wwwlogs  # логи"
