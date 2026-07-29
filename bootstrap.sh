#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  CAMPUS BOOTSTRAP — восстановление всей инфраструктуры из GitHub
# ═══════════════════════════════════════════════════════════════════════
#
#  С нуля на новой машине (2 команды):
#
#    git clone https://github.com/LandauAudioserver/campus-infra.git
#    cd campus-infra && bash bootstrap.sh all
#
#  Если нужен доступ к приватному campus-secrets (токен GitHub):
#    GH_TOKEN=ghp_xxx bash bootstrap.sh all
#
#  Использование:
#    bash bootstrap.sh all       — сервер + nctk
#    bash bootstrap.sh server    — только сервер
#    bash bootstrap.sh nctk      — только nctk (по SSH)
#    bash bootstrap.sh secrets   — только подтянуть/обновить секреты
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="${SECRETS_DIR:-$HOME/projects/campus-secrets}"
SECRETS_REPO_SSH="git@github.com:LandauAudioserver/campus-secrets.git"
SECRETS_REPO_HTTPS="https://github.com/LandauAudioserver/campus-secrets.git"
GH_TOKEN="${GH_TOKEN:-}"

NCTK_HOST="${NCTK_HOST:-10.20.0.41}"
NCTK_USER="${NCTK_USER:-nctk}"
VM1_HOST="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"
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
        CLONE_URL="https://${GH_TOKEN}@github.com/LandauAudioserver/campus-secrets.git"
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
    for f in narimanov.config.env genclik.config.env; do
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

    # Скрипт синхронизации времени nctk
    SYNC_SCRIPT="$HOME/scripts/sync-nctk-time.sh"
    if [[ ! -f "$SYNC_SCRIPT" ]]; then
        mkdir -p "$HOME/scripts"
        cp -f "$REPO_DIR/scripts/sync-nctk-time.sh" "$SYNC_SCRIPT" 2>/dev/null || true
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

# ─── 3. СЕКРЕТЫ NCTK ───────────────────────────────────────────────────
apply_nctk_secrets() {
    [[ ! -d "$SECRETS_DIR" ]] && return 0

    echo "[nctk] Копирую секреты на nctk..."
    SCP="scp $SSH_OPTS"

    $SCP "$SECRETS_DIR/nctk/telegram-bot.config.env" \
        "${NCTK_USER}@${NCTK_HOST}:/home/nctk/telegram-campus-bot/config.env" 2>/dev/null && \
        ok "telegram-bot.config.env" || warn "telegram-bot.config.env — пропущено"

    $SCP "$SECRETS_DIR/nctk/cron_notify.env" \
        "${NCTK_USER}@${NCTK_HOST}:/home/nctk/cron_notify.env" 2>/dev/null && \
        ok "cron_notify.env" || warn "cron_notify.env — пропущено"

    ssh $SSH_OPTS "${NCTK_USER}@${NCTK_HOST}" \
        "chmod 600 /home/nctk/cron_notify.env /home/nctk/telegram-campus-bot/config.env" \
        2>/dev/null || true
}

# ─── 3b. СЕКРЕТЫ VM1 ────────────────────────────────────────────────────
apply_vm1_secrets() {
    [[ ! -d "$SECRETS_DIR" ]] && return 0

    echo "[vm1] Копирую секреты на vm1..."
    SCP="scp $SSH_OPTS"

    $SCP "$SECRETS_DIR/vm1/telegram-bot.config.env" \
        "${VM1_USER}@${VM1_HOST}:/home/vm1/telegram-campus-bot/config.env" 2>/dev/null && \
        ok "telegram-bot.config.env" || warn "telegram-bot.config.env — пропущено"

    ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" \
        "chmod 600 /home/vm1/telegram-campus-bot/config.env" 2>/dev/null || true
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
    SYNC_SCRIPT="$HOME/scripts/sync-nctk-time.sh"
    if [[ -f "$SYNC_SCRIPT" ]]; then
        CRON_TMP="/tmp/campus_cron_$$"
        crontab -l 2>/dev/null > "$CRON_TMP" || true
        ENTRY="0 * * * * $SYNC_SCRIPT >> $HOME/log/nctk-timesync.log 2>&1"
        if ! grep -qF "$ENTRY" "$CRON_TMP" 2>/dev/null; then
            echo "$ENTRY" >> "$CRON_TMP"
            crontab "$CRON_TMP"
            ok "Cron: sync-nctk-time.sh (каждый час)"
        fi
        rm -f "$CRON_TMP"
    fi
}

# ─── 5. NCTK ───────────────────────────────────────────────────────────
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

restore_nctk() {
    _restore_client "nctk" "$NCTK_HOST" "$NCTK_USER" "nctk" "apply_nctk_secrets"
}

restore_vm1() {
    _restore_client "vm1" "$VM1_HOST" "$VM1_USER" "vm1" "apply_vm1_secrets"
}

# ─── ЗАПУСК ────────────────────────────────────────────────────────────
fetch_secrets || true  # не прерываем если секреты недоступны

case "$TARGET" in
    all)
        restore_server
        restore_nctk
        restore_vm1
        ;;
    server)
        restore_server
        ;;
    nctk)
        restore_nctk
        ;;
    vm1)
        restore_vm1
        ;;
    clients)
        restore_nctk
        restore_vm1
        ;;
    secrets)
        apply_server_secrets
        ;;
    *)
        echo "Использование: $0 [all|server|nctk|vm1|clients|secrets]"
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
