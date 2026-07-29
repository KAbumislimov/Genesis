#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  CAMPUS-INFRA — Полное восстановление на новом сервере
#  Использование: bash RESTORE.sh
# ═══════════════════════════════════════════════════════════════
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="$HOME/projects/campus-secrets"
DATA_DIR="$REPO_DIR/data"

info "=== CAMPUS-INFRA RESTORE ==="
info "Repo: $REPO_DIR"

# ── 1. Зависимости ──────────────────────────────────────────────
info "Проверка зависимостей..."
command -v docker   >/dev/null 2>&1 || error "Docker не установлен. Установи: https://docs.docker.com/engine/install/"
command -v git      >/dev/null 2>&1 || error "Git не установлен"
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 не установлен"

# ── 2. Секреты ──────────────────────────────────────────────────
info "Проверка секретов (campus-secrets)..."
if [ ! -d "$SECRETS_DIR" ]; then
    warn "campus-secrets не найден — клонирую..."
    git clone git@github.com:MediaAudioserver/campus-secrets.git "$SECRETS_DIR" \
        || error "Не удалось клонировать campus-secrets. Добавь SSH-ключ на GitHub."
fi

# Копируем .env если нет
ENV_FILE="$REPO_DIR/webui/.env"
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$SECRETS_DIR/webui/.env" ]; then
        cp "$SECRETS_DIR/webui/.env" "$ENV_FILE"
        info ".env скопирован из campus-secrets"
    else
        error ".env не найден ни в репо ни в campus-secrets. Создай $ENV_FILE"
    fi
else
    info ".env уже существует"
fi

# ── 3. Данные (wallpapers, db) ──────────────────────────────────
info "Создание директорий data/..."
mkdir -p "$DATA_DIR/webui/wallpapers"
mkdir -p "$DATA_DIR/webui/avatars"
mkdir -p "$DATA_DIR/webui/voices"
mkdir -p "$DATA_DIR/webui/announces"
mkdir -p "$DATA_DIR/helpdesk/uploads"

# Восстановление wallpapers из бэкапа если есть
if [ -d "$HOME/campus-backups/wallpapers" ]; then
    info "Восстановление обоев из campus-backups..."
    cp -n "$HOME/campus-backups/wallpapers/"* "$DATA_DIR/webui/wallpapers/" 2>/dev/null || true
fi

# ── 4. Сборка и запуск ─────────────────────────────────────────
info "Сборка Docker образов..."
cd "$REPO_DIR"
docker compose build

info "Запуск сервисов..."
docker compose up -d

# ── 5. Проверка ─────────────────────────────────────────────────
sleep 3
info "Статус контейнеров:"
docker compose ps

echo ""
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Восстановление завершено!${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo ""
echo "  Веб-интерфейс: http://localhost:5000"
echo "  Логи:          docker compose logs -f campus-webui"
echo "  Остановить:    docker compose down"
echo ""
echo -e "${YELLOW}Если первый запуск — войди и смени пароль admin!${NC}"
