#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  CAMPUS BOOTSTRAP — восстановление всей инфраструктуры из GitHub
# ═══════════════════════════════════════════════════════════════════════
#
#  С нуля на новой машине (2 команды):
#
#    git clone https://github.com/MediaAudioserver/campus-infra.git
#    cd campus-infra && bash bootstrap.sh all
#
#  Если нужен доступ к приватному campus-secrets (токен GitHub):
#    GH_TOKEN=ghp_xxx bash bootstrap.sh all
#
#  Использование:
#    bash bootstrap.sh all       — сервер + client1
#    bash bootstrap.sh server    — только сервер
#    bash bootstrap.sh client1      — только client1 (по SSH)
#    bash bootstrap.sh secrets   — только подтянуть/обновить секреты
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="${SECRETS_DIR:-$HOME/projects/campus-secrets}"
SECRETS_REPO_SSH="git@github.com:MediaAudioserver/campus-secrets.git"
SECRETS_REPO_HTTPS="https://github.com/MediaAudioserver/campus-secrets.git"
GH_TOKEN="${GH_TOKEN:-}"

CLIENT1_HOST="${CLIENT1_HOST:-10.20.0.41}"
CLIENT1_USER="${CLIENT1_USER:-client1}"
CLIENT2_HOST="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30 -o BatchMode=yes"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="-i $SSH_KEY $SSH_OPTS"

TARGET="${1:-all}"

# ─── helpers ───────────────────────────────────────────────────────────
ok()   { echo "  ✅ $*"; }
warn() { echo "  ⚠️  $*"; }
info() { echo "  ℹ️  $*"; }
die()  { echo "  ❌ $*" >&2; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   CAMPUS BOOTSTRAP — $(date '+%Y-%m-%d %H:%M')       ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║   Репо:   $REPO_DIR"
echo "║   Цель:   $TARGET"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ─── 1. СЕКРЕТЫ ────────────────────────────────────────────────────────
fetch_secrets() {
    echo "[secrets] Получаю campus-secrets..."

    if [[ -d "$SECRETS_DIR/.git" ]]; then
        git -C "$SECRETS_DIR" pull --quiet
        ok "Секреты обновлены: $SECRETS_DIR"
        return 0
    fi

    # Пробуем SSH
    if ssh -o BatchMode=yes -o ConnectTimeout=5 git@github.com true 2>/dev/null; then
        git clone --quiet "$SECRETS_REPO_SSH" "$SECRETS_DIR"
        ok "Секреты клонированы (SSH)"
        return 0
    fi

    # Пробуем HTTPS с токеном
    if [[ -n "$GH_TOKEN" ]]; then
        CLONE_URL="https://${GH_TOKEN}@github.com/MediaAudioserver/campus-secrets.git"
        git clone --quiet "$CLONE_URL" "$SECRETS_DIR"
        ok "Секреты клонированы (HTTPS+token)"
        return 0
    fi

    warn "campus-secrets недоступен."
    warn "Варианты:"
    warn "  1. GH_TOKEN=ghp_xxx bash bootstrap.sh $TARGET"
    warn "  2. Добавь SSH ключ GitHub и повтори"
    warn "  3. Скопируй $SECRETS_DIR вручную и повтори"
    return 1
}

# ─── 2. СЕКРЕТЫ СЕРВЕРА ────────────────────────────────────────────────
apply_server_secrets() {
    [[ ! -d "$SECRETS_DIR" ]] && { warn "Секреты не найдены — пропускаю"; return 0; }

    echo "[secrets] Применяю секреты на сервер..."

    # .env
    [[ -f "$SECRETS_DIR/server/.env" ]] && cp -f "$SECRETS_DIR/server/.env" "$REPO_DIR/.env" && ok ".env"

    # Bot configs
    for f in client1.config.env client2.config.env; do
        bot="${f%.config.env}"
        src="$SECRETS_DIR/server/$f"
        dst="$REPO_DIR/bots/$bot/config.env"
        [[ -f "$src" ]] && cp -f "$src" "$dst" && ok "$bot/config.env"
    done

    # SSH ключ campus_bot
    for src in \
        "$SECRETS_DIR/server/campus_bot" \
        "$SECRETS_DIR/ssh/campus_bot" \
        "$SECRETS_DIR/campus_bot"
    do
        if [[ -f "$src" ]]; then
            mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
            cp -f "$src"       "$HOME/.ssh/campus_bot"
            cp -f "${src}.pub" "$HOME/.ssh/campus_bot.pub" 2>/dev/null || true
            chmod 600 "$HOME/.ssh/campus_bot"
            ok "campus_bot SSH ключ → ~/.ssh/campus_bot"
            break
        fi
    done

    # Автодобавить SSH_KEY_DIR в .env
    ENV_FILE="$REPO_DIR/.env"
    if [[ -f "$ENV_FILE" ]] && ! grep -q "SSH_KEY_DIR" "$ENV_FILE"; then
        echo "SSH_KEY_DIR=$HOME/.ssh" >> "$ENV_FILE"
        ok "SSH_KEY_DIR=$HOME/.ssh добавлен в .env"
    fi

    # Скрипт синхронизации времени client1
    SYNC_SCRIPT="$HOME/scripts/sync-client1-time.sh"
    if [[ ! -f "$SYNC_SCRIPT" ]]; then
        mkdir -p "$HOME/scripts"
        cp -f "$REPO_DIR/scripts/sync-client1-time.sh" "$SYNC_SCRIPT" 2>/dev/null || true
        chmod +x "$SYNC_SCRIPT" 2>/dev/null || true
    fi

    # Backup секреты
    [[ -f "$SECRETS_DIR/backup.env" ]] && \
        cp -f "$SECRETS_DIR/backup.env" "$HOME/projects/campus-secrets/backup.env" 2>/dev/null || true

    # Кроны бэкапов
    mkdir -p "$HOME/campus-backups" "$HOME/log"
    BACKUP_SCRIPT="$REPO_DIR/scripts/backup/backup-weekly.sh"
    if [[ -f "$BACKUP_SCRIPT" ]]; then
        chmod +x "$BACKUP_SCRIPT"
        CRON_TMP="/tmp/campus_backup_cron_$$"
        crontab -l 2>/dev/null > "$CRON_TMP" || true
        ENTRY="0 7 * * 1 $BACKUP_SCRIPT >> $HOME/log/backup.log 2>&1"
        if ! grep -qF "backup-weekly.sh" "$CRON_TMP" 2>/dev/null; then
            echo "# Campus weekly backup (Mon 07:00)" >> "$CRON_TMP"
            echo "$ENTRY" >> "$CRON_TMP"
            crontab "$CRON_TMP"
            ok "Backup cron: каждый понедельник 07:00"
        fi
        rm -f "$CRON_TMP"
    fi
}

# ─── 3. СЕКРЕТЫ CLIENT1 ───────────────────────────────────────────────────
apply_client1_secrets() {
    [[ ! -d "$SECRETS_DIR" ]] && return 0

    echo "[client1] Копирую секреты на client1..."
    SCP="scp $SSH_OPTS"

    $SCP "$SECRETS_DIR/client1/telegram-bot.config.env" \
        "${CLIENT1_USER}@${CLIENT1_HOST}:/home/client1/telegram-campus-bot/config.env" 2>/dev/null && \
        ok "telegram-bot.config.env" || warn "telegram-bot.config.env — пропущено"

    $SCP "$SECRETS_DIR/client1/cron_notify.env" \
        "${CLIENT1_USER}@${CLIENT1_HOST}:/home/client1/cron_notify.env" 2>/dev/null && \
        ok "cron_notify.env" || warn "cron_notify.env — пропущено"

    ssh $SSH_OPTS "${CLIENT1_USER}@${CLIENT1_HOST}" \
        "chmod 600 /home/client1/cron_notify.env /home/client1/telegram-campus-bot/config.env" \
        2>/dev/null || true
}

# ─── 3b. СЕКРЕТЫ CLIENT2 ────────────────────────────────────────────────────
apply_client2_secrets() {
    [[ ! -d "$SECRETS_DIR" ]] && return 0

    echo "[client2] Копирую секреты на client2..."
    SCP="scp $SSH_OPTS"

    $SCP "$SECRETS_DIR/client2/telegram-bot.config.env" \
        "${CLIENT2_USER}@${CLIENT2_HOST}:/home/client2/telegram-campus-bot/config.env" 2>/dev/null && \
        ok "telegram-bot.config.env" || warn "telegram-bot.config.env — пропущено"

    ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" \
        "chmod 600 /home/client2/telegram-campus-bot/config.env" 2>/dev/null || true
}

# ─── 4. СЕРВЕР ─────────────────────────────────────────────────────────
restore_server() {
    echo ""
    echo "════════════════════════════════════"
    echo "  СЕРВЕР"
    echo "════════════════════════════════════"

    apply_server_secrets
    bash "$REPO_DIR/machines/server/install.sh"

    # Cron синхронизации времени
    SYNC_SCRIPT="$HOME/scripts/sync-client1-time.sh"
    if [[ -f "$SYNC_SCRIPT" ]]; then
        CRON_TMP="/tmp/campus_cron_$$"
        crontab -l 2>/dev/null > "$CRON_TMP" || true
        ENTRY="0 * * * * $SYNC_SCRIPT >> $HOME/log/client1-timesync.log 2>&1"
        if ! grep -qF "$ENTRY" "$CRON_TMP" 2>/dev/null; then
            echo "$ENTRY" >> "$CRON_TMP"
            crontab "$CRON_TMP"
            ok "Cron: sync-client1-time.sh (каждый час)"
        fi
        rm -f "$CRON_TMP"
    fi
}

# ─── 5. CLIENT1 ───────────────────────────────────────────────────────────
_restore_client() {
    local NAME="$1" HOST="$2" USER="$3" MACHINE_DIR="$4" SECRETS_FN="$5"
    echo ""
    echo "════════════════════════════════════"
    echo "  $NAME ($HOST)"
    echo "════════════════════════════════════"

    if ! ssh $SSH_OPTS "${USER}@${HOST}" "true" 2>/dev/null; then
        warn "SSH до $NAME ($HOST) недоступен — пропускаю"
        info "Вручную: scp $MACHINE_DIR/ → $NAME && bash install.sh"
        return 0
    fi
    ok "SSH до $NAME доступен"

    TMP_REMOTE="/tmp/campus-restore-$(date +%s)"
    ssh $SSH_OPTS "${USER}@${HOST}" "mkdir -p $TMP_REMOTE"
    scp $SSH_OPTS -r "$REPO_DIR/machines/$MACHINE_DIR/" "${USER}@${HOST}:${TMP_REMOTE}/" >/dev/null

    echo "[$NAME] Запускаю install.sh..."
    ssh $SSH_OPTS "${USER}@${HOST}" "bash ${TMP_REMOTE}/${MACHINE_DIR}/install.sh"
    ssh $SSH_OPTS "${USER}@${HOST}" "rm -rf ${TMP_REMOTE}"

    "$SECRETS_FN"
    ok "$NAME восстановлен"
}

restore_client1() {
    _restore_client "client1" "$CLIENT1_HOST" "$CLIENT1_USER" "client1" "apply_client1_secrets"
}

restore_client2() {
    _restore_client "client2" "$CLIENT2_HOST" "$CLIENT2_USER" "client2" "apply_client2_secrets"
}

# ─── ЗАПУСК ────────────────────────────────────────────────────────────
fetch_secrets || true  # не прерываем если секреты недоступны

case "$TARGET" in
    all)
        restore_server
        restore_client1
        restore_client2
        ;;
    server)
        restore_server
        ;;
    client1)
        restore_client1
        ;;
    client2)
        restore_client2
        ;;
    clients)
        restore_client1
        restore_client2
        ;;
    secrets)
        apply_server_secrets
        ;;
    *)
        echo "Использование: $0 [all|server|client1|client2|clients|secrets]"
        exit 1
        ;;
esac

SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'SERVER_IP')"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   BOOTSTRAP ЗАВЕРШЁН ✅                          ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║   🌐 Web UI:     http://${SERVER_IP}:8090        ║"
echo "║   📊 Grafana:    http://${SERVER_IP}:3000        ║"
echo "║   📈 Prometheus: http://${SERVER_IP}:9090        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  Статус: docker compose ps"
echo "  Логи:   docker compose logs -f campus-webui"
echo ""
