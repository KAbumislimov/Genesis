#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  CAMPUS WEEKLY BACKUP — полный бэкап всех машин
#  Запускается на CentOS (kamran) каждый понедельник в 07:00
#
#  Cron (добавить командой: crontab -e):
#    0 7 * * 1 /home/kamran/projects/campus-infra/scripts/backup/backup-weekly.sh >> /home/kamran/log/backup.log 2>&1
#
#  Что делает:
#    1. Создаёт папку /home/kamran/campus-backups/YYYY-MM-DD/
#    2. Удаляет прошлые папки с бэкапами
#    3. Делает бэкап конфигов client1 (10.20.0.41) → client1-config.tar.gz
#    4. Делает бэкап конфигов client2 (10.70.0.41) → client2-config.tar.gz
#    5. rsync музыки client1 → campus-backups/music-client1/ (только изменения)
#    6. rsync музыки client2  → campus-backups/music-client2/  (только изменения)
#    7. Делает бэкап CentOS (Docker volumes, configs) → centos.tar.gz
#    8. Пишет отчёт report.txt
#    9. Отправляет уведомления в Telegram + email
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Конфигурация ──────────────────────────────────────────────────────
BACKUP_BASE="/home/kamran/campus-backups"
DATE=$(date '+%Y-%m-%d')
TIME=$(date '+%H:%M')
BACKUP_DIR="$BACKUP_BASE/$DATE"
LOG_DIR="/home/kamran/log"
LOG_FILE="$LOG_DIR/backup-$DATE.log"
SSH_KEY="/home/kamran/.ssh/campus_bot"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30 -o BatchMode=yes -i $SSH_KEY"

CLIENT1_HOST="10.20.0.41"
CLIENT1_USER="client1"
CLIENT1_MUSIC_PATH="/mnt/music/Media/"
CLIENT2_HOST="10.70.0.41"
CLIENT2_USER="client2"
CLIENT2_MUSIC_PATH="/home/client2/Media/"

# Telegram (читаем из секретов или используем значения по умолчанию)
SECRETS_FILE="/home/kamran/projects/campus-secrets/backup.env"
[[ -f "$SECRETS_FILE" ]] && source "$SECRETS_FILE"

BOT_TOKEN="${BACKUP_BOT_TOKEN:-8280240854:AAGqh4CkyGp0a_-rDumfZmjH_1k8M7Jeljo}"
TG_CHATS=("${BACKUP_TG_CHAT1:--1002883515031}" "${BACKUP_TG_CHAT2:--1003491812335}")

EMAIL_WORK="${BACKUP_EMAIL_WORK:-admin@example.edu}"
EMAIL_PERSONAL="${BACKUP_EMAIL_PERSONAL:-kamran19910101@gmail.com}"

# ─── Логирование ───────────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$BACKUP_BASE"
exec > >(tee -a "$LOG_FILE") 2>&1

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $*"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠️  $*"; }
fail() { echo "[$(date '+%H:%M:%S')] ❌ $*"; }

log "═══════════════════════════════════════"
log " CAMPUS BACKUP START — $DATE $TIME"
log "═══════════════════════════════════════"

# ─── Статусы для отчёта ────────────────────────────────────────────────
declare -A STATUS
declare -A SIZES
ERRORS=()

# ─── 1. Создаём папку бэкапа, удаляем старые ──────────────────────────
log "[1/7] Создаю папку бэкапа..."
# Удаляем все предыдущие папки (только dated dirs, не music-*)
for old_dir in "$BACKUP_BASE"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]; do
    [[ -d "$old_dir" && "$old_dir" != "$BACKUP_DIR" ]] && {
        log "  Удаляю старый бэкап: $old_dir"
        rm -rf "$old_dir"
    }
done
mkdir -p "$BACKUP_DIR"
ok "Папка бэкапа: $BACKUP_DIR"

# ─── 2. Бэкап конфигов CLIENT1 ───────────────────────────────────────────
log "[2/7] Бэкап CLIENT1 (10.20.0.41)..."
backup_client1() {
    if ! ssh $SSH_OPTS "$CLIENT1_USER@$CLIENT1_HOST" "true" 2>/dev/null; then
        warn "CLIENT1 недоступен, пропускаю"
        STATUS[client1]="❌ недоступен"
        ERRORS+=("client1: SSH недоступен")
        return 1
    fi

    ssh $SSH_OPTS "$CLIENT1_USER@$CLIENT1_HOST" bash << 'CLIENT1_PACK'
set -e
TMP_DIR="/tmp/campus-backup-client1-$$"
mkdir -p "$TMP_DIR/systemd" "$TMP_DIR/home/bin" "$TMP_DIR/netplan" "$TMP_DIR/promtail"

# systemd units
for f in campus-mpv campus-telegram-bot campus-player-watchdog campus-player-watchdog \
          node_exporter promtail; do
    cp /etc/systemd/system/${f}.service "$TMP_DIR/systemd/" 2>/dev/null || true
    cp /etc/systemd/system/${f}.timer   "$TMP_DIR/systemd/" 2>/dev/null || true
done

# crontab
crontab -l > "$TMP_DIR/crontab.txt" 2>/dev/null || echo "(empty)" > "$TMP_DIR/crontab.txt"

# scripts
for f in campus-cron-media-local.sh campus-cron-stop-local.sh campus-playerctl \
          bell-play-with-notify.sh cron_notify.sh; do
    cp /home/client1/$f "$TMP_DIR/home/" 2>/dev/null || true
done
cp -r /home/client1/bin/. "$TMP_DIR/home/bin/" 2>/dev/null || true
cp /usr/local/bin/campus-playerctl "$TMP_DIR/home/" 2>/dev/null || true

# samba + network
cp /etc/samba/smb.conf "$TMP_DIR/" 2>/dev/null || true
cp /etc/netplan/*.yaml "$TMP_DIR/netplan/" 2>/dev/null || true

# promtail config
cp /home/client1/campus-monitoring/promtail/config.yaml "$TMP_DIR/promtail/" 2>/dev/null || true

# package list
dpkg --get-selections > "$TMP_DIR/packages.txt" 2>/dev/null || true

# hostname + OS info
uname -a > "$TMP_DIR/system-info.txt"
cat /etc/os-release >> "$TMP_DIR/system-info.txt"

# music file list (not the files themselves - those are rsync'd separately)
find /mnt/music/ -type f | sort > "$TMP_DIR/music-files.txt" 2>/dev/null || true

tar -czf /tmp/client1-config.tar.gz -C /tmp "campus-backup-client1-$$"
rm -rf "$TMP_DIR"
echo "OK"
CLIENT1_PACK

    if scp $SSH_OPTS "$CLIENT1_USER@$CLIENT1_HOST:/tmp/client1-config.tar.gz" "$BACKUP_DIR/client1-config.tar.gz" 2>/dev/null; then
        ssh $SSH_OPTS "$CLIENT1_USER@$CLIENT1_HOST" "rm -f /tmp/client1-config.tar.gz" 2>/dev/null || true
        SIZE=$(du -sh "$BACKUP_DIR/client1-config.tar.gz" 2>/dev/null | cut -f1)
        ok "client1-config.tar.gz ($SIZE)"
        STATUS[client1]="✅ конфиг ($SIZE)"
        SIZES[client1_config]="$SIZE"
    else
        fail "Не удалось скачать бэкап client1"
        STATUS[client1]="❌ ошибка scp"
        ERRORS+=("client1: ошибка scp config")
        return 1
    fi
}
backup_client1 || true

# ─── 3. Бэкап конфигов CLIENT2 ────────────────────────────────────────────
log "[3/7] Бэкап CLIENT2 (10.70.0.41)..."
backup_client2() {
    if ! ssh $SSH_OPTS "$CLIENT2_USER@$CLIENT2_HOST" "true" 2>/dev/null; then
        warn "CLIENT2 недоступен, пропускаю"
        STATUS[client2]="❌ недоступен"
        ERRORS+=("client2: SSH недоступен")
        return 1
    fi

    ssh $SSH_OPTS "$CLIENT2_USER@$CLIENT2_HOST" bash << 'CLIENT2_PACK'
set -e
TMP_DIR="/tmp/campus-backup-client2-$$"
mkdir -p "$TMP_DIR/systemd" "$TMP_DIR/home/bin" "$TMP_DIR/netplan" "$TMP_DIR/promtail"

for f in campus-mpv campus-telegram-bot campus-player-watchdog campus-player-watchdog \
          node_exporter promtail; do
    cp /etc/systemd/system/${f}.service "$TMP_DIR/systemd/" 2>/dev/null || true
    cp /etc/systemd/system/${f}.timer   "$TMP_DIR/systemd/" 2>/dev/null || true
done

crontab -l > "$TMP_DIR/crontab.txt" 2>/dev/null || echo "(empty)" > "$TMP_DIR/crontab.txt"

for f in campus-cron-media-local.sh campus-cron-media-client2.sh campus-cron-stop-local.sh \
          campus-playerctl; do
    cp /home/client2/$f "$TMP_DIR/home/" 2>/dev/null || true
done
cp -r /home/client2/bin/. "$TMP_DIR/home/bin/" 2>/dev/null || true

cp /etc/netplan/*.yaml "$TMP_DIR/netplan/" 2>/dev/null || true
cp /home/client2/campus-monitoring/promtail/config.yaml "$TMP_DIR/promtail/" 2>/dev/null || true

dpkg --get-selections > "$TMP_DIR/packages.txt" 2>/dev/null || true
uname -a > "$TMP_DIR/system-info.txt"
cat /etc/os-release >> "$TMP_DIR/system-info.txt"

find /home/client2/Media/ -type f | sort > "$TMP_DIR/music-files.txt" 2>/dev/null || true

tar -czf /tmp/client2-config.tar.gz -C /tmp "campus-backup-client2-$$"
rm -rf "$TMP_DIR"
echo "OK"
CLIENT2_PACK

    if scp $SSH_OPTS "$CLIENT2_USER@$CLIENT2_HOST:/tmp/client2-config.tar.gz" "$BACKUP_DIR/client2-config.tar.gz" 2>/dev/null; then
        ssh $SSH_OPTS "$CLIENT2_USER@$CLIENT2_HOST" "rm -f /tmp/client2-config.tar.gz" 2>/dev/null || true
        SIZE=$(du -sh "$BACKUP_DIR/client2-config.tar.gz" 2>/dev/null | cut -f1)
        ok "client2-config.tar.gz ($SIZE)"
        STATUS[client2]="✅ конфиг ($SIZE)"
        SIZES[client2_config]="$SIZE"
    else
        fail "Не удалось скачать бэкап client2"
        STATUS[client2]="❌ ошибка scp"
        ERRORS+=("client2: ошибка scp config")
        return 1
    fi
}
backup_client2 || true

# ─── 4. rsync музыки CLIENT1 ─────────────────────────────────────────────
log "[4/7] rsync музыки CLIENT1..."
backup_music_client1() {
    MUSIC_DST="$BACKUP_BASE/music-client1"
    mkdir -p "$MUSIC_DST"
    if rsync -az --no-perms --no-owner --no-group --delete --stats \
        -e "ssh $SSH_OPTS" \
        "$CLIENT1_USER@$CLIENT1_HOST:$CLIENT1_MUSIC_PATH" "$MUSIC_DST/" 2>&1 | tail -5; then
        SIZE=$(du -sh "$MUSIC_DST" 2>/dev/null | cut -f1)
        ok "Музыка client1: $SIZE → $MUSIC_DST"
        STATUS[client1_music]="✅ $SIZE"
        SIZES[client1_music]="$SIZE"
    else
        fail "rsync музыки client1"
        STATUS[client1_music]="❌ ошибка rsync"
        ERRORS+=("client1: ошибка rsync музыки")
    fi
}
backup_music_client1 || true

# ─── 5. rsync музыки CLIENT2 ──────────────────────────────────────────────
log "[5/7] rsync музыки CLIENT2..."
backup_music_client2() {
    MUSIC_DST="$BACKUP_BASE/music-client2"
    mkdir -p "$MUSIC_DST"
    if rsync -az --no-perms --no-owner --no-group --delete --stats \
        -e "ssh $SSH_OPTS" \
        "$CLIENT2_USER@$CLIENT2_HOST:$CLIENT2_MUSIC_PATH" "$MUSIC_DST/" 2>&1 | tail -5; then
        SIZE=$(du -sh "$MUSIC_DST" 2>/dev/null | cut -f1)
        ok "Музыка client2: $SIZE → $MUSIC_DST"
        STATUS[client2_music]="✅ $SIZE"
        SIZES[client2_music]="$SIZE"
    else
        fail "rsync музыки client2"
        STATUS[client2_music]="❌ ошибка rsync"
        ERRORS+=("client2: ошибка rsync музыки")
    fi
}
backup_music_client2 || true

# ─── 6. Бэкап CentOS ──────────────────────────────────────────────────
log "[6/7] Бэкап CentOS..."
backup_centos() {
    CENTOS_TMP="$BACKUP_DIR/centos-tmp"
    mkdir -p "$CENTOS_TMP/docker-volumes" "$CENTOS_TMP/configs" "$CENTOS_TMP/systemd"

    REPO="/home/kamran/projects/campus-infra"

    # docker-compose.yaml
    cp "$REPO/docker-compose.yaml" "$CENTOS_TMP/configs/" 2>/dev/null || true

    # Дополнительные конфиги
    cp -r "$REPO/config/" "$CENTOS_TMP/configs/campus-infra-config/" 2>/dev/null || true

    # Кронтаб
    crontab -l > "$CENTOS_TMP/crontab.txt" 2>/dev/null || echo "(empty)" > "$CENTOS_TMP/crontab.txt"

    # Список пакетов
    rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' 2>/dev/null | sort > "$CENTOS_TMP/packages-rpm.txt" || true

    # System info
    uname -a > "$CENTOS_TMP/system-info.txt"
    cat /etc/os-release >> "$CENTOS_TMP/system-info.txt" 2>/dev/null || true

    # Docker volume: webui_data (DB, wallpapers, avatars, emojis)
    if docker run --rm \
        -v campus-infra_webui_data:/vol:ro \
        alpine tar -czf - /vol 2>/dev/null > "$CENTOS_TMP/docker-volumes/webui_data.tar.gz"; then
        SIZE=$(du -sh "$CENTOS_TMP/docker-volumes/webui_data.tar.gz" 2>/dev/null | cut -f1)
        log "  webui_data: $SIZE"
    else
        warn "webui_data volume: ошибка"
    fi

    # Docker volume: grafana_data (дашборды, настройки)
    if docker run --rm \
        -v campus-infra_grafana_data:/vol:ro \
        alpine tar -czf - /vol 2>/dev/null > "$CENTOS_TMP/docker-volumes/grafana_data.tar.gz"; then
        SIZE=$(du -sh "$CENTOS_TMP/docker-volumes/grafana_data.tar.gz" 2>/dev/null | cut -f1)
        log "  grafana_data: $SIZE"
    else
        warn "grafana_data volume: ошибка"
    fi

    # Создаём итоговый архив
    tar -czf "$BACKUP_DIR/centos.tar.gz" -C "$BACKUP_DIR" "centos-tmp"
    rm -rf "$CENTOS_TMP"

    SIZE=$(du -sh "$BACKUP_DIR/centos.tar.gz" 2>/dev/null | cut -f1)
    ok "centos.tar.gz ($SIZE)"
    STATUS[centos]="✅ $SIZE"
    SIZES[centos]="$SIZE"
}
backup_centos || {
    fail "Бэкап CentOS: ошибка"
    STATUS[centos]="❌ ошибка"
    ERRORS+=("centos: ошибка бэкапа")
}

# ─── 7. Финальный отчёт ───────────────────────────────────────────────
log "[7/7] Составляю отчёт..."

TOTAL_SIZE=$(du -sh "$BACKUP_BASE" 2>/dev/null | cut -f1)
DATED_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
MUSIC_CLIENT1_SIZE=$(du -sh "$BACKUP_BASE/music-client1" 2>/dev/null | cut -f1 || echo "—")
MUSIC_CLIENT2_SIZE=$(du -sh "$BACKUP_BASE/music-client2" 2>/dev/null | cut -f1 || echo "—")
DISK_FREE=$(df -h /home/kamran | tail -1 | awk '{print $4}')
BACKUP_DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Список файлов в dated backup dir
FILES_LIST=$(ls -lh "$BACKUP_DIR" 2>/dev/null | grep -v "^total" | awk '{print $9, $5}' | column -t)

REPORT="
╔════════════════════════════════════════════════════╗
║  CAMPUS BACKUP REPORT — $DATE
╠════════════════════════════════════════════════════╣

Дата:          $BACKUP_DATE
Папка:         $BACKUP_DIR

─── Конфиги + Docker volumes ($DATED_SIZE) ──────────
  client1:        ${STATUS[client1]:-—}
  client2:         ${STATUS[client2]:-—}
  centos:      ${STATUS[centos]:-—}

─── Музыка (rsync, только изменения) ────────────────
  client1:        ${STATUS[client1_music]:-—}   ($MUSIC_CLIENT1_SIZE)
  client2:         ${STATUS[client2_music]:-—}   ($MUSIC_CLIENT2_SIZE)

─── Файлы в архиве ───────────────────────────────────
$FILES_LIST

─── Диск ────────────────────────────────────────────
  Всего бэкапов:  $TOTAL_SIZE
  Свободно /home: $DISK_FREE
"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    REPORT+="
─── ОШИБКИ ──────────────────────────────────────────"
    for e in "${ERRORS[@]}"; do REPORT+="
  ⚠️  $e"; done
fi

REPORT+="
╚════════════════════════════════════════════════════╝"

echo "$REPORT"
echo "$REPORT" > "$BACKUP_DIR/report.txt"
ok "Отчёт сохранён: $BACKUP_DIR/report.txt"

# ─── Telegram уведомление ─────────────────────────────────────────────
TG_STATUS_ICON="✅"
[[ ${#ERRORS[@]} -gt 0 ]] && TG_STATUS_ICON="⚠️"

TG_MSG="$TG_STATUS_ICON *CAMPUS BACKUP* — $DATE

*Конфиги:*
• client1: ${STATUS[client1]:-—}
• client2: ${STATUS[client2]:-—}
• CentOS: ${STATUS[centos]:-—}

*Музыка (rsync):*
• client1: ${STATUS[client1_music]:-—}
• client2: ${STATUS[client2_music]:-—}

*Итого:* $TOTAL_SIZE | Диск свободно: $DISK_FREE
*Папка:* \`$BACKUP_DIR\`"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    TG_MSG+="

*Ошибки:*"
    for e in "${ERRORS[@]}"; do TG_MSG+="
• $e"; done
fi

send_telegram() {
    local msg="$1"
    for chat_id in "${TG_CHATS[@]}"; do
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d chat_id="$chat_id" \
            -d text="$msg" \
            -d parse_mode="Markdown" \
            --max-time 15 \
            > /dev/null 2>&1 || warn "Telegram: ошибка отправки в $chat_id"
    done
}
send_telegram "$TG_MSG" && ok "Telegram уведомление отправлено"

# ─── Email уведомление ────────────────────────────────────────────────
send_email() {
    SEND_SCRIPT="$(dirname "$0")/send-email.py"
    [[ ! -f "$SEND_SCRIPT" ]] && { warn "Email: скрипт не найден ($SEND_SCRIPT)"; return 0; }
    [[ -z "${BACKUP_SMTP_USER:-}" ]] && { warn "Email: BACKUP_SMTP_USER не задан в $SECRETS_FILE"; return 0; }

    python3 "$SEND_SCRIPT" \
        --smtp-host "${BACKUP_SMTP_HOST:-smtp.gmail.com}" \
        --smtp-port "${BACKUP_SMTP_PORT:-587}" \
        --smtp-user "$BACKUP_SMTP_USER" \
        --smtp-pass "$BACKUP_SMTP_PASS" \
        --from    "$BACKUP_SMTP_USER" \
        --to      "$EMAIL_WORK,$EMAIL_PERSONAL" \
        --subject "Campus Backup $TG_STATUS_ICON $DATE" \
        --body    "$REPORT" \
        && ok "Email отправлен: $EMAIL_WORK, $EMAIL_PERSONAL" \
        || warn "Email: ошибка отправки"
}
send_email || true

log "═══════════════════════════════════════"
log " CAMPUS BACKUP DONE — $(date '+%H:%M:%S')"
log "═══════════════════════════════════════"
