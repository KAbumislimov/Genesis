#!/bin/bash
# Переключение campus-mpv с systemd на автозапуск в сессии пользователя client2.
# Звук работает при ручном запуске, но не через systemd — запускаем mpv в GUI-сессии.
#
# Выполнить НА client2 (в SSH-сессии).
set -e

echo "=== Настройка mpv через autostart (вместо systemd) ==="

# 1. Создаём каталог при загрузке (если ещё нет)
echo "1. Создание /run/campus-player..."
sudo tee /etc/tmpfiles.d/campus-player.conf << 'EOF'
d /run/campus-player 0775 client2 audio -
EOF

# 2. Отключаем systemd-сервис
echo "2. Отключение campus-mpv.service..."
sudo systemctl stop campus-mpv 2>/dev/null || true
sudo systemctl disable campus-mpv 2>/dev/null || true

# 3. Autostart для mpv при входе пользователя client2
echo "3. Добавление autostart..."
mkdir -p /home/client2/.config/autostart
cat > /home/client2/.config/autostart/campus-mpv.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Campus MPV
Exec=mpv --no-video --vo=null --idle=yes --force-window=no --audio-display=no --input-ipc-server=/run/campus-player/mpv.sock --audio-device=alsa/plughw:1,0
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

chown client2:client2 /home/client2/.config/autostart/campus-mpv.desktop

# 4. Создаём каталог сейчас (для текущей сессии)
sudo mkdir -p /run/campus-player
sudo chown client2:audio /run/campus-player
sudo chmod 775 /run/campus-player

echo ""
echo "Готово. Дальше:"
echo "  1. Перезагрузите client2: sudo reboot"
echo "  2. После входа client2 в графическую сессию (автологин) mpv запустится сам."
echo "  3. Cron будет воспроизводить музыку по расписанию."
echo ""
echo "Проверка без перезагрузки (если client2 уже залогинен в GUI):"
echo "  Запустите вручную: mpv --no-video --vo=null --idle=yes --force-window=no --audio-display=no --input-ipc-server=/run/campus-player/mpv.sock --audio-device=alsa/plughw:1,0 &"
echo "  Затем: campus-playerctl play /home/client2/Media/5/1peremena.mp3"
