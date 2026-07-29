#!/bin/bash
# Переход campus-mpv на user-сервис (systemd --user) с linger.
# Решает проблему SIGKILL при запуске через cron — system-сервис может убиваться.
#
# Выполнить НА vm1 под sudo (или с правами на создание dirs).
set -e

echo "=== Переход campus-mpv на user-сервис vm1 ==="

# 1. Включаем linger — сессия vm1 живёт без входа
sudo loginctl enable-linger vm1

# 2. Останавливаем и отключаем system-сервис
sudo systemctl stop campus-mpv 2>/dev/null || true
sudo systemctl disable campus-mpv 2>/dev/null || true

# 3. Создаём user unit для vm1
mkdir -p /home/vm1/.config/systemd/user
sudo tee /home/vm1/.config/systemd/user/campus-mpv.service << 'EOF'
[Unit]
Description=Campus MP3 player (mpv idle) — vm1 user
After=sound.target
Wants=sound.target

[Service]
Type=simple
# Отключаем ограничения
PrivateUsers=false
PrivateDevices=false
ProtectSystem=false
NoNewPrivileges=false

ExecStartPre=/bin/bash -c 'mkdir -p /run/campus-player && chown vm1:audio /run/campus-player && chmod 775 /run/campus-player'
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

sudo chown vm1:vm1 /home/vm1/.config/systemd/user/campus-mpv.service

# 4. ExecStartPre требует root — делаем через systemd tmpfiles или отдельный скрипт
# Упрощаем: создаём dir заранее с правильными правами
sudo mkdir -p /run/campus-player
sudo chown vm1:audio /run/campus-player
sudo chmod 775 /run/campus-player

# Убираем ExecStartPre — dir уже создан, при перезагрузке нужен другой способ
sudo sed -i 's/ExecStartPre=.*//' /home/vm1/.config/systemd/user/campus-mpv.service
sudo sed -i '/^$/N;/^\n$/d' /home/vm1/.config/systemd/user/campus-mpv.service

# Восстанавливаем unit без ExecStartPre (dir создаётся при загрузке через другой механизм)
sudo tee /home/vm1/.config/systemd/user/campus-mpv.service << 'EOF'
[Unit]
Description=Campus MP3 player (mpv idle) — vm1 user
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
echo 'd /run/campus-player 0775 vm1 audio - -' | sudo tee /etc/tmpfiles.d/campus-player.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/campus-player.conf

# 5. Запускаем user-сессию (если ещё не запущена) и user-сервис
VM1_UID=$(id -u vm1)
sudo systemctl start user@$VM1_UID 2>/dev/null || true
sleep 2
sudo -u vm1 env XDG_RUNTIME_DIR=/run/user/$VM1_UID systemctl --user daemon-reload
sudo -u vm1 env XDG_RUNTIME_DIR=/run/user/$VM1_UID systemctl --user enable campus-mpv
sudo -u vm1 env XDG_RUNTIME_DIR=/run/user/$VM1_UID systemctl --user start campus-mpv

echo ""
echo "Готово. Проверка:"
echo "  sudo -u vm1 env XDG_RUNTIME_DIR=/run/user/$VM1_UID systemctl --user status campus-mpv"
echo "  campus-playerctl play /home/vm1/Landau/5/6peremena.mp3"
echo ""
echo "После перезагрузки: linger обеспечит автозапуск user-сессии vm1."
