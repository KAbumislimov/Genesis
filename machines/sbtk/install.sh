#!/bin/bash
# Установка sbtk-клиента с нуля (Ubuntu 22.04).
# Запуск: bash install.sh
# Что делает:
#   - Устанавливает mpv, socat, ffmpeg, python3
#   - Настраивает /run/campus-player/ (tmpfiles)
#   - Устанавливает campus-mpv как user-сервис (systemd --user)
#   - Устанавливает watchdog-таймер (системный)
#   - Устанавливает телеграм-бот
#   - Устанавливает crontab (расписание перемен)
#   - Устанавливает promtail + node_exporter (если есть)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SBTK_USER="${SBTK_USER:-sbtk}"
SBTK_HOME="/home/$SBTK_USER"
BOT_DIR="$SBTK_HOME/telegram-campus-bot"
MEDIA_DIR="$SBTK_HOME/Media"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       SBTK CLIENT INSTALL                 ║"
echo "╚══════════════════════════════════════════╝"
echo "  Пользователь: $SBTK_USER"
echo "  Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ─────────────────────────────────────────────
# 1. ЗАВИСИМОСТИ
# ─────────────────────────────────────────────
echo "[1/6] Системные пакеты..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    mpv socat ffmpeg python3 curl wget jq \
    alsa-utils pulseaudio pulseaudio-utils >/dev/null
echo "  ✅ mpv socat ffmpeg python3 pulseaudio — OK"

# ─────────────────────────────────────────────
# 2. /run/campus-player (tmpfiles)
# ─────────────────────────────────────────────
echo "[2/6] /run/campus-player..."
sudo mkdir -p /run/campus-player
sudo chown "$SBTK_USER:audio" /run/campus-player
sudo chmod 2775 /run/campus-player

# tmpfiles.d — пересоздавать после перезагрузки
echo "d /run/campus-player 2775 $SBTK_USER audio -" | \
    sudo tee /etc/tmpfiles.d/campus-player.conf >/dev/null
echo "  ✅ /run/campus-player"

# ─────────────────────────────────────────────
# 3. СКРИПТЫ
# ─────────────────────────────────────────────
echo "[3/6] Скрипты..."
for f in campus-cron-media-local.sh campus-cron-stop-local.sh campus-cron-media-notify.sh campus-cron-stop-notify.sh cron_notify.sh campus-playerctl notify-ssh-login.sh; do
    src="$SCRIPT_DIR/scripts/$f"
    dst="$SBTK_HOME/$f"
    if [[ -f "$src" ]]; then
        cp -f "$src" "$dst"
        chmod +x "$dst"
        echo "  + $f"
    fi
done

# SSH login notification → profile.d
sudo cp -f "$SCRIPT_DIR/scripts/notify-ssh-login.sh" /etc/profile.d/campus-notify-login.sh
sudo chmod +x /etc/profile.d/campus-notify-login.sh
echo "  ✅ SSH login notification"

# Симлинк campus-playerctl в PATH
if [[ ! -f "/usr/local/bin/campus-playerctl" ]]; then
    sudo ln -sf "$SBTK_HOME/campus-playerctl" /usr/local/bin/campus-playerctl
fi

# ─────────────────────────────────────────────
# 4. SYSTEMD СЕРВИСЫ
# ─────────────────────────────────────────────
echo "[4/6] Systemd сервисы..."

# campus-mpv — user-сервис (запускается под sbtk)
SYSTEMD_USER_DIR="$SBTK_HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
cp -f "$SCRIPT_DIR/systemd/campus-mpv.service" "$SYSTEMD_USER_DIR/campus-mpv.service"

# Включаем linger чтобы user-сервис стартовал без логина
sudo loginctl enable-linger "$SBTK_USER"

# Запускаем user-сервис
sudo -u "$SBTK_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SBTK_USER")" \
    systemctl --user daemon-reload
sudo -u "$SBTK_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SBTK_USER")" \
    systemctl --user enable --now campus-mpv
echo "  ✅ campus-mpv (user service)"

# Watchdog (системный) — перезапускает campus-mpv если упал
for f in campus-player-watchdog.service campus-player-watchdog.timer; do
    sudo cp -f "$SCRIPT_DIR/systemd/$f" "/etc/systemd/system/$f"
done
sudo systemctl daemon-reload
sudo systemctl enable --now campus-player-watchdog.timer
echo "  ✅ campus-player-watchdog.timer"

# ─────────────────────────────────────────────
# 5. TELEGRAM BOT
# ─────────────────────────────────────────────
echo "[5/6] Telegram бот..."
mkdir -p "$BOT_DIR"
cp -f "$SCRIPT_DIR/bot/bot.py" "$BOT_DIR/bot.py"

if [[ ! -f "$BOT_DIR/config.env" ]]; then
    cp -f "$SCRIPT_DIR/bot/config.env.example" "$BOT_DIR/config.env"
    echo "  ⚠️  Заполни $BOT_DIR/config.env (BOT_TOKEN, LOG_GROUP_ID)"
fi

# Systemd сервис бота
sudo cp -f "$SCRIPT_DIR/systemd/campus-telegram-bot.service" \
    /etc/systemd/system/campus-telegram-bot.service
sudo systemctl daemon-reload

if grep -q "BOT_TOKEN=your_bot_token" "$BOT_DIR/config.env" 2>/dev/null; then
    echo "  ⚠️  Бот не запущен — сначала заполни config.env, затем:"
    echo "     sudo systemctl enable --now campus-telegram-bot"
else
    sudo systemctl enable --now campus-telegram-bot
    echo "  ✅ campus-telegram-bot запущен"
fi

# ─────────────────────────────────────────────
# 6. CRONTAB
# ─────────────────────────────────────────────
echo "[6/6] Crontab (расписание перемен)..."
mkdir -p "$SBTK_HOME/Media"

CRON_TMP="/tmp/campus_sbtk_cron_$$"
crontab -u "$SBTK_USER" -l 2>/dev/null > "$CRON_TMP" || true

# Проверяем не установлен ли уже
if ! grep -q "campus-cron-media-local" "$CRON_TMP" 2>/dev/null; then
    cat "$SCRIPT_DIR/crontab" >> "$CRON_TMP"
    crontab -u "$SBTK_USER" "$CRON_TMP"
    echo "  ✅ Crontab установлен"
else
    echo "  ✅ Crontab уже есть"
fi
rm -f "$CRON_TMP"

# ─────────────────────────────────────────────
# PROMTAIL / NODE EXPORTER (опционально)
# ─────────────────────────────────────────────
if [[ -f "$SBTK_HOME/bin/promtail" ]]; then
    cp -f "$SCRIPT_DIR/promtail-config.yaml" "$SBTK_HOME/promtail/config.yaml" 2>/dev/null || true
    sudo cp -f "$SCRIPT_DIR/systemd/promtail.service" /etc/systemd/system/promtail.service
    sudo cp -f "$SCRIPT_DIR/systemd/node_exporter.service" /etc/systemd/system/node_exporter.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now promtail node_exporter 2>/dev/null || true
    echo "  ✅ promtail + node_exporter"
fi

# ─────────────────────────────────────────────
# 7. АУДИО-АНАЛИЗАТОР (FFT для визуализатора в веб-панели)
# ─────────────────────────────────────────────
echo "[7/7] Аудио-анализатор..."
mkdir -p "$SBTK_HOME/campus-monitoring"
cp -f "$SCRIPT_DIR/campus-monitoring/audio-analyzer.py" "$SBTK_HOME/campus-monitoring/audio-analyzer.py"
mkdir -p "$SYSTEMD_USER_DIR"
cp -f "$SCRIPT_DIR/systemd/campus-audio-analyzer.service" "$SYSTEMD_USER_DIR/campus-audio-analyzer.service"
sudo -u "$SBTK_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SBTK_USER")" \
    systemctl --user daemon-reload
sudo -u "$SBTK_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SBTK_USER")" \
    systemctl --user enable --now campus-audio-analyzer
echo "  ✅ campus-audio-analyzer (user service)"

# ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       SBTK УСТАНОВКА ЗАВЕРШЕНА ✅         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Статус mpv:  sudo -u sbtk XDG_RUNTIME_DIR=/run/user/\$(id -u sbtk) systemctl --user status campus-mpv"
echo "  Тест звука:  campus-playerctl play $MEDIA_DIR/1/1peremena.mp3"
echo "  Логи бота:   journalctl -u campus-telegram-bot -f"
echo "  Заполни:     $BOT_DIR/config.env"
echo ""
echo "⚠️  Если этот install.sh запущен НЕ через scripts/recover-campus-machine.sh —"
echo "    SSH-ключи, музыку и control-бот нужно поднять отдельно (см. scripts/recover-campus-machine.sh)."
echo "    Cockpit (опционально) — скопируй scripts/restore-client2.sh как scripts/restore-sbtk.sh и поправь под эту машину."
echo ""
