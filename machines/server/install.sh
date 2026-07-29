#!/bin/bash
# Установка campus-server с нуля на чистой ОС.
# Запуск: bash install.sh
# Что делает:
#   - Устанавливает git, curl, Docker
#   - Проверяет .env и SSH-ключи
#   - Поднимает все Docker контейнеры (включая webui)
#   - Прописывает cron (синхронизация времени nctk, мониторинг диска)

set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SERVER_IP="$(hostname -I | awk '{print $1}')"
LOG_DIR="$HOME/log"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       CAMPUS SERVER INSTALL              ║"
echo "╚══════════════════════════════════════════╝"
echo "  Репо:   $REPO_DIR"
echo "  IP:     $SERVER_IP"
echo "  Время:  $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ─────────────────────────────────────────────
# 1. СИСТЕМНЫЕ ЗАВИСИМОСТИ
# ─────────────────────────────────────────────
echo "[1/6] Системные зависимости..."

install_pkg() {
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y --no-install-recommends "$@" >/dev/null
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$@" >/dev/null
    elif command -v yum &>/dev/null; then
        sudo yum install -y "$@" >/dev/null
    fi
}

for pkg in git curl openssh-client; do
    command -v "${pkg%%-*}" &>/dev/null || install_pkg "$pkg"
done
echo "  ✅ git curl ssh — OK"

# ─────────────────────────────────────────────
# 2. DOCKER
# ─────────────────────────────────────────────
echo "[2/6] Docker..."
if ! command -v docker &>/dev/null; then
    echo "  Установка Docker..."
    curl -fsSL https://get.docker.com | sudo bash >/dev/null 2>&1
    sudo usermod -aG docker "$USER"
    echo ""
    echo "  ⚠️  Docker установлен. Нужно перезайти в сессию:"
    echo "      newgrp docker && bash $0"
    exit 0
fi
echo "  ✅ $(docker --version)"

# ─────────────────────────────────────────────
# 3. SSH КЛЮЧИ
# ─────────────────────────────────────────────
echo "[3/6] SSH ключи..."
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys" "$HOME/.ssh/known_hosts"
chmod 600 "$HOME/.ssh/authorized_keys"

KEY_FILE="$HOME/.ssh/campus_bot"
if [[ ! -f "$KEY_FILE" ]]; then
    # Ищем ключ в campus-secrets
    SECRETS_DIR="${SECRETS_DIR:-$HOME/projects/campus-secrets}"
    for src in \
        "$SECRETS_DIR/server/campus_bot" \
        "$SECRETS_DIR/ssh/campus_bot" \
        "$SECRETS_DIR/campus_bot"
    do
        if [[ -f "$src" ]]; then
            cp -f "$src"     "$KEY_FILE"
            cp -f "${src}.pub" "${KEY_FILE}.pub" 2>/dev/null || true
            chmod 600 "$KEY_FILE"
            echo "  ✅ campus_bot ← $src"
            break
        fi
    done
    if [[ ! -f "$KEY_FILE" ]]; then
        echo "  ⚠️  campus_bot не найден — webui и SSH к nctk не будут работать"
        echo "     Положи ключ в $KEY_FILE (или в campus-secrets/server/campus_bot)"
    fi
else
    echo "  ✅ campus_bot уже есть"
fi

# ─────────────────────────────────────────────
# 4. .env — КОНФИГИ
# ─────────────────────────────────────────────
echo "[4/6] Конфиги .env..."
if [[ ! -f "$REPO_DIR/.env" ]]; then
    if [[ -f "$REPO_DIR/.env.example" ]]; then
        cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    fi
    echo "  ⚠️  Создан $REPO_DIR/.env из примера — проверь!"
fi

# Автодобавить SSH_KEY_DIR если нет
if ! grep -q "SSH_KEY_DIR" "$REPO_DIR/.env" 2>/dev/null; then
    echo "SSH_KEY_DIR=$HOME/.ssh" >> "$REPO_DIR/.env"
    echo "  + SSH_KEY_DIR добавлен в .env"
fi

# Bot configs
for bot in narimanov genclik; do
    cfg="$REPO_DIR/bots/$bot/config.env"
    example="$REPO_DIR/bots/$bot/config.env.example"
    [[ ! -f "$cfg" && -f "$example" ]] && cp "$example" "$cfg" && echo "  ⚠️  Заполни $cfg"
done
echo "  ✅ .env OK"

# ─────────────────────────────────────────────
# 5. NGINX + mDNS (leg.local)
# ─────────────────────────────────────────────
echo "[5/6] Nginx + avahi (leg.local)..."

NGINX_CONF="$REPO_DIR/machines/server/campus-audio.nginx.conf"
AVAHI_CONF="$REPO_DIR/machines/server/avahi-daemon.conf"

if command -v nginx &>/dev/null; then
    if [[ -f "$NGINX_CONF" ]]; then
        if ! diff -q "$NGINX_CONF" /etc/nginx/conf.d/campus-audio.conf &>/dev/null; then
            sudo cp -f "$NGINX_CONF" /etc/nginx/conf.d/campus-audio.conf
            sudo nginx -t -q 2>/dev/null && sudo nginx -s reload 2>/dev/null && echo "  ✅ nginx: leg.local/audio/server → :8090"
        else
            echo "  ✅ nginx: campus-audio.conf уже актуален"
        fi
    fi
else
    echo "  ⚠️  nginx не найден — пропускаю (установи nginx и скопируй $NGINX_CONF → /etc/nginx/conf.d/)"
fi

if command -v avahi-daemon &>/dev/null && [[ -f "$AVAHI_CONF" ]]; then
    if ! diff -q "$AVAHI_CONF" /etc/avahi/avahi-daemon.conf &>/dev/null; then
        sudo cp -f "$AVAHI_CONF" /etc/avahi/avahi-daemon.conf
        sudo systemctl restart avahi-daemon 2>/dev/null && echo "  ✅ avahi: сервер виден как leg.local"
    else
        echo "  ✅ avahi: конфиг уже актуален"
    fi
fi

# ─────────────────────────────────────────────
# 6. DOCKER СТЕК
# ─────────────────────────────────────────────
echo "[6/6] Docker стек..."
cd "$REPO_DIR"

# Убедимся что все образы собраны
docker compose build campus-webui 2>&1 | grep -E "Built|ERROR" || true

docker compose \
    --profile bot \
    --profile logs \
    --profile watchdog \
    --profile recovery \
    --profile webui \
    up -d

echo "  ✅ Контейнеры запущены"
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null | head -15

# ─────────────────────────────────────────────
# 6. CRON — СЕРВЕР
# ─────────────────────────────────────────────
echo "[6/6] Cron задания сервера..."
mkdir -p "$LOG_DIR"

CRON_FILE="/tmp/campus_crontab_$$"
crontab -l 2>/dev/null > "$CRON_FILE" || true

add_cron() {
    local entry="$1"
    if ! grep -qF "$entry" "$CRON_FILE" 2>/dev/null; then
        echo "$entry" >> "$CRON_FILE"
        echo "  + $entry"
    fi
}

# Шапка если файл пустой
if [[ ! -s "$CRON_FILE" ]]; then
    cat >> "$CRON_FILE" << 'EOF'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
MAILTO=""
EOF
fi

# Устанавливаем sync-скрипт если нет
SYNC_SRC="$REPO_DIR/scripts/sync-nctk-time.sh"
SYNC_DST="$HOME/scripts/sync-nctk-time.sh"
if [[ -f "$SYNC_SRC" && ! -f "$SYNC_DST" ]]; then
    mkdir -p "$HOME/scripts"
    cp -f "$SYNC_SRC" "$SYNC_DST"
    chmod +x "$SYNC_DST"
    echo "  + sync-nctk-time.sh → $SYNC_DST"
fi

# Синхронизация времени nctk (каждый час)
[[ -f "$SYNC_DST" ]] && add_cron "0 * * * * $SYNC_DST >> $LOG_DIR/nctk-timesync.log 2>&1"
# Мониторинг диска (каждый час)
DISK_MON="$REPO_DIR/scripts/check-disk-and-cleanup.sh"
[[ -f "$DISK_MON" ]] && add_cron "0 * * * * $DISK_MON >> $LOG_DIR/disk-monitor.log 2>&1"

crontab "$CRON_FILE"
rm -f "$CRON_FILE"
echo "  ✅ Cron настроен"

# ─────────────────────────────────────────────
# ГОТОВО
# ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       УСТАНОВКА ЗАВЕРШЕНА ✅             ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  🌐 Web UI:    http://leg.local/  или  http://${SERVER_IP}:8090/"
echo "  📊 Grafana:   http://${SERVER_IP}:3000   (admin / из .env)"
echo "  📈 Prometheus:http://${SERVER_IP}:9090"
echo ""
echo "  Логи: docker compose logs -f campus-webui"
echo "  Стоп: docker compose --profile bot --profile logs --profile watchdog --profile recovery --profile webui down"
echo ""
