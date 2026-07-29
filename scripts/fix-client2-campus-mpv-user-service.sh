#!/bin/bash
# Переход campus-mpv на user-сервис (systemd --user) с linger.
# Решает проблему SIGKILL при запуске через cron — system-сервис может убиваться.
#
# Выполнить НА client2 под sudo (или с правами на создание dirs).
set -e

echo "=== Переход campus-mpv на user-сервис client2 ==="

# 1. Включаем linger — сессия client2 живёт без входа
sudo loginctl enable-linger client2

# 2. Останавливаем и отключаем system-сервис
sudo systemctl stop campus-mpv 2>/dev/null || true
sudo systemctl disable campus-mpv 2>/dev/null || true

# 3. Создаём user unit для client2
mkdir -p /home/client2/.config/systemd/user
sudo tee /home/client2/.config/systemd/user/campus-mpv.service << 'EOF'
[Unit]
Description=Campus MP3 player (mpv idle) — client2 user
After=sound.target
Wants=sound.target

[Service]
Type=simple
# Отключаем ограничения
PrivateUsers=false
PrivateDevices=false
ProtectSystem=false
NoNewPrivileges=false

ExecStartPre=/bin/bash -c 'mkdir -p /run/campus-player && chown client2:audio /run/campus-player && chmod 775 /run/campus-player'
ExecStart=/usr/bin/mpv \
  --no-video \
  --vo=null \
  --idle=yes \
  --force-window=no \
  --audio-display=no \
  --volume-max=160 \
  --input-ipc-server=/run/campus-player/mpv.sock

Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

sudo chown client2:client2 /home/client2/.config/systemd/user/campus-mpv.service

# 4. ExecStartPre требует root — делаем через systemd tmpfiles или отдельный скрипт
# Упрощаем: создаём dir заранее с правильными правами
sudo mkdir -p /run/campus-player
sudo chown client2:audio /run/campus-player
sudo chmod 775 /run/campus-player

# Убираем ExecStartPre — dir уже создан, при перезагрузке нужен другой способ
sudo sed -i 's/ExecStartPre=.*//' /home/client2/.config/systemd/user/campus-mpv.service
sudo sed -i '/^$/N;/^\n$/d' /home/client2/.config/systemd/user/campus-mpv.service

# Восстанавливаем unit без ExecStartPre (dir создаётся при загрузке через другой механизм)
sudo tee /home/client2/.config/systemd/user/campus-mpv.service << 'EOF'
[Unit]
Description=Campus MP3 player (mpv idle) — client2 user
After=sound.target
Wants=sound.target

[Service]
Type=simple
PrivateUsers=false
PrivateDevices=false
ProtectSystem=false
NoNewPrivileges=false

ExecStart=/usr/bin/mpv \
  --no-video \
  --vo=null \
  --idle=yes \
  --force-window=no \
  --audio-display=no \
  --volume-max=160 \
  --input-ipc-server=/run/campus-player/mpv.sock

Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Создаём tmpfiles для /run/campus-player при загрузке
echo 'd /run/campus-player 0775 client2 audio - -' | sudo tee /etc/tmpfiles.d/campus-player.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/campus-player.conf

# 5. Запускаем user-сессию (если ещё не запущена) и user-сервис
CLIENT2_UID=$(id -u client2)
sudo systemctl start user@$CLIENT2_UID 2>/dev/null || true
sleep 2
sudo -u client2 env XDG_RUNTIME_DIR=/run/user/$CLIENT2_UID systemctl --user daemon-reload
sudo -u client2 env XDG_RUNTIME_DIR=/run/user/$CLIENT2_UID systemctl --user enable campus-mpv
sudo -u client2 env XDG_RUNTIME_DIR=/run/user/$CLIENT2_UID systemctl --user start campus-mpv

echo ""
echo "Готово. Проверка:"
echo "  sudo -u client2 env XDG_RUNTIME_DIR=/run/user/$CLIENT2_UID systemctl --user status campus-mpv"
echo "  campus-playerctl play /home/client2/Media/5/6peremena.mp3"
echo ""
echo "После перезагрузки: linger обеспечит автозапуск user-сессии client2."
