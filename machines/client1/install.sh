#!/bin/bash
# Установка/восстановление client1 с нуля из этого репозитория.
# Запуск: bash install.sh
# Что делает: ставит пакеты, копирует скрипты, сервисы, кронтаб,
#              скачивает node_exporter и promtail, запускает сервисы.

set -e
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="/home/client1"
NODE_EXPORTER_VERSION="1.6.1"
PROMTAIL_VERSION="2.9.5"
ARCH="linux-amd64"

echo "=== Установка client1 ==="

# 1. Пакеты
echo "[1/7] Установка пакетов..."
sudo apt-get update -qq
sudo apt-get install -y -qq mpv socat jq python3 curl alsa-utils

# 2. Скрипты в ~/
echo "[2/7] Копирование скриптов..."
cp -f "$REPO_DIR/scripts/campus-cron-media-local.sh" "$HOME_DIR/"
cp -f "$REPO_DIR/scripts/campus-cron-stop-local.sh"   "$HOME_DIR/"
cp -f "$REPO_DIR/scripts/campus-playerctl"             "$HOME_DIR/"
cp -f "$REPO_DIR/scripts/bell-play-with-notify.sh"    "$HOME_DIR/"
cp -f "$REPO_DIR/scripts/cron_notify.sh"               "$HOME_DIR/"
chmod +x "$HOME_DIR/campus-cron-media-local.sh" \
         "$HOME_DIR/campus-cron-stop-local.sh" \
         "$HOME_DIR/campus-playerctl" \
         "$HOME_DIR/bell-play-with-notify.sh" \
         "$HOME_DIR/cron_notify.sh"

# SSH login notification
cp -f "$REPO_DIR/scripts/notify-ssh-login.sh" "$HOME_DIR/"
chmod +x "$HOME_DIR/notify-ssh-login.sh"
sudo cp -f "$REPO_DIR/scripts/notify-ssh-login.sh" /etc/profile.d/campus-notify-login.sh
sudo chmod +x /etc/profile.d/campus-notify-login.sh

# campus-playerctl также в /usr/local/bin
sudo cp -f "$REPO_DIR/scripts/campus-playerctl" /usr/local/bin/campus-playerctl
sudo chmod +x /usr/local/bin/campus-playerctl

# 3. ~/bin/
echo "[3/7] Копирование bin/..."
mkdir -p "$HOME_DIR/bin"
cp -f "$REPO_DIR/bin/"*.sh "$HOME_DIR/bin/"
chmod +x "$HOME_DIR/bin/"*.sh

# 4. Telegram-бот
echo "[4/7] Установка Telegram-бота..."
mkdir -p "$HOME_DIR/telegram-campus-bot"
cp -f "$REPO_DIR/bot/bot.py" "$HOME_DIR/telegram-campus-bot/"
if [[ ! -f "$HOME_DIR/telegram-campus-bot/config.env" ]]; then
    cp "$REPO_DIR/config.env.example" "$HOME_DIR/telegram-campus-bot/config.env"
    echo "  ! ЗАПОЛНИ $HOME_DIR/telegram-campus-bot/config.env (BOT_TOKEN, LOG_GROUP_ID)"
fi
if [[ ! -f "$HOME_DIR/cron_notify.env" ]]; then
    echo "BOT_TOKEN=" > "$HOME_DIR/cron_notify.env"
    echo "LOG_GROUP_ID=" >> "$HOME_DIR/cron_notify.env"
    chmod 600 "$HOME_DIR/cron_notify.env"
    echo "  ! ЗАПОЛНИ $HOME_DIR/cron_notify.env (BOT_TOKEN, LOG_GROUP_ID)"
fi

# 5. node_exporter + promtail
echo "[5/7] Установка node_exporter и promtail..."
mkdir -p "$HOME_DIR/campus-monitoring/bin" "$HOME_DIR/campus-monitoring/promtail"

if [[ ! -f "$HOME_DIR/campus-monitoring/bin/node_exporter" ]]; then
    TMP=$(mktemp -d)
    NE_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.${ARCH}.tar.gz"
    echo "  Скачиваю node_exporter ${NODE_EXPORTER_VERSION}..."
    curl -fsSL "$NE_URL" | tar -xz -C "$TMP"
    cp "$TMP/node_exporter-${NODE_EXPORTER_VERSION}.${ARCH}/node_exporter" "$HOME_DIR/campus-monitoring/bin/"
    chmod +x "$HOME_DIR/campus-monitoring/bin/node_exporter"
    rm -rf "$TMP"
fi

if [[ ! -f "$HOME_DIR/campus-monitoring/bin/promtail" ]]; then
    TMP=$(mktemp -d)
    PT_URL="https://github.com/grafana/loki/releases/download/v${PROMTAIL_VERSION}/promtail-${ARCH}.zip"
    echo "  Скачиваю promtail ${PROMTAIL_VERSION}..."
    curl -fsSL "$PT_URL" -o "$TMP/promtail.zip"
    unzip -q "$TMP/promtail.zip" -d "$TMP"
    cp "$TMP/promtail-${ARCH}" "$HOME_DIR/campus-monitoring/bin/promtail"
    chmod +x "$HOME_DIR/campus-monitoring/bin/promtail"
    rm -rf "$TMP"
fi

cp -f "$REPO_DIR/promtail/config.yaml" "$HOME_DIR/campus-monitoring/promtail/config.yaml"

# 6. Systemd сервисы
echo "[6/7] Установка systemd сервисов..."
sudo cp -f "$REPO_DIR/systemd/campus-mpv.service"              /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/campus-telegram-bot.service"     /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/campus-player-watchdog.service"  /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/campus-player-watchdog.timer"    /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/node_exporter.service"           /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/promtail.service"                /etc/systemd/system/
sudo cp -f "$REPO_DIR/systemd/campus-audio-analyzer.service"   /etc/systemd/system/

sudo systemctl daemon-reload
mkdir -p "$HOME_DIR/logs"
mkdir -p /var/lib/campus-player/inbox 2>/dev/null || sudo mkdir -p /var/lib/campus-player/inbox && sudo chown client1:client1 /var/lib/campus-player/inbox

# Аудио-анализатор (FFT для визуализатора в веб-панели)
mkdir -p "$HOME_DIR/campus-monitoring"
cp -f "$REPO_DIR/campus-monitoring/audio-analyzer.py" "$HOME_DIR/campus-monitoring/audio-analyzer.py"

sudo systemctl enable --now campus-mpv
sudo systemctl enable --now campus-telegram-bot
sudo systemctl enable --now campus-player-watchdog.timer
sudo systemctl enable --now node_exporter
sudo systemctl enable --now promtail
sudo systemctl enable --now campus-audio-analyzer

# 7. Crontab
echo "[7/7] Установка crontab..."
crontab "$REPO_DIR/crontab"

echo ""
echo "=== Установка завершена ==="
echo ""
echo "Проверь статус сервисов:"
echo "  systemctl status campus-mpv campus-telegram-bot node_exporter promtail campus-audio-analyzer"
echo ""
echo "Если ещё не заполнил секреты:"
echo "  nano ~/telegram-campus-bot/config.env   (BOT_TOKEN, LOG_GROUP_ID)"
echo "  nano ~/cron_notify.env                  (BOT_TOKEN, LOG_GROUP_ID)"
echo ""
echo "Samba пароль (для доступа с Windows):"
echo "  sudo smbpasswd -a client1"
echo ""
echo "⚠️  ЕЩЁ НУЖНО СДЕЛАТЬ (с центрального сервера, не отсюда):"
echo "  1. bash scripts/setup-recovery-ssh-keys.sh   — доступ сервера сюда без пароля"
echo "  2. bash scripts/restore-client1.sh              — Cockpit"
echo "  3. Восстановить содержимое /mnt/music/Media из бэкапа (см. docs/DISASTER-RECOVERY.md)"
