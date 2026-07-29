#!/bin/bash
# Исправление campus-mpv.service для работы БЕЗ входа пользователя (после перезагрузки).
# Проблема: systemd ограничивает доступ к звуку. Отключаем ограничения.
#
# Выполнить НА client2.
set -e

echo "=== Исправление campus-mpv для работы без логина ==="

# Обновляем основной unit — добавляем отключение ограничений systemd
sudo tee /etc/systemd/system/campus-mpv.service << 'EOF'
[Unit]
Description=Campus MP3 player (mpv idle) — client2
After=sound.target systemd-udev-settle.service
Wants=sound.target

[Service]
Type=simple
User=client2
Group=audio
SupplementaryGroups=audio

# Отключаем ограничения systemd — иначе нет доступа к звуку
PrivateUsers=false
PrivateDevices=false
ProtectSystem=false
NoNewPrivileges=false
ReadWritePaths=/dev/snd /run/campus-player

PermissionsStartOnly=true
ExecStartPre=/bin/bash -c 'mkdir -p /run/campus-player && chown client2:audio /run/campus-player && chmod 775 /run/campus-player'
ExecStart=/usr/bin/mpv \
  --no-video \
  --vo=null \
  --idle=yes \
  --force-window=no \
  --audio-display=no \
  --volume-max=160 \
  --input-ipc-server=/run/campus-player/mpv.sock \
  --audio-device=alsa/plughw:1,0

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Удаляем override'ы — они переопределяют ExecStart
sudo rm -f /etc/systemd/system/campus-mpv.service.d/audio.conf \
          /etc/systemd/system/campus-mpv.service.d/override.conf \
          /etc/systemd/system/campus-mpv.service.d/restart.conf

# Перезагружаем
sudo systemctl daemon-reload
sudo systemctl enable campus-mpv
sudo systemctl restart campus-mpv

echo ""
echo "Готово. Проверка:"
echo "  systemctl status campus-mpv"
echo "  campus-playerctl play /home/client2/Media/5/1peremena.mp3"
echo ""
echo "После перезагрузки cron будет работать без входа пользователя."
