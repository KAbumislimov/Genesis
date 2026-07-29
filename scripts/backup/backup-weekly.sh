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
#    3. Делает бэкап конфигов nctk (10.20.0.41) → nctk-config.tar.gz
#    4. Делает бэкап конфигов vm1 (10.70.0.41) → vm1-config.tar.gz
#    5. rsync музыки nctk → campus-backups/music-nctk/ (только изменения)
#    6. rsync музыки vm1  → campus-backups/music-vm1/  (только изменения)
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

NCTK_HOST="10.20.0.41"
NCTK_USER="nctk"
NCTK_MUSIC_PATH="/mnt/music/Landau/"
VM1_HOST="10.70.0.41"
VM1_USER="vm1"
VM1_MUSIC_PATH="/home/vm1/Landau/"

# Telegram (читаем из секретов или используем значения по умолчанию)
SECRETS_FILE="/home/kamran/projects/campus-secrets/backup.env"
[[ -f "$SECRETS_FILE" ]] && source "$SECRETS_FILE"

BOT_TOKEN="${BACKUP_BOT_TOKEN:-8280240854:AAGqh4CkyGp0a_-rDumfZmjH_1k8M7Jeljo}"
TG_CHATS=("${BACKUP_TG_CHAT1:--1002883515031}" "${BACKUP_TG_CHAT2:--1003491812335}")

EMAIL_WORK="${BACKUP_EMAIL_WORK:-k.abumislimov@leg.edu.az}"
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

# ─── 2. Бэкап конфигов NCTK ───────────────────────────────────────────
log "[2/7] Бэкап NCTK (10.20.0.41)..."
backup_nctk() {
    if ! ssh $SSH_OPTS "$NCTK_USER@$NCTK_HOST" "true" 2>/dev/null; then
        warn "NCTK недоступен, пропускаю"
        STATUS[nctk]="❌ недоступен"
        ERRORS+=("nctk: SSH недоступен")
        return 1
    fi

    ssh $SSH_OPTS "$NCTK_USER@$NCTK_HOST" bash << 'NCTK_PACK'
set -e
TMP_DIR="/tmp/campus-backup-nctk-$$"
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
for f in campus-cron-landau-local.sh campus-cron-stop-local.sh campus-playerctl \
          bell-play-with-notify.sh cron_notify.sh; do
    cp /home/nctk/$f "$TMP_DIR/home/" 2>/dev/null || true
done
cp -r /home/nctk/bin/. "$TMP_DIR/home/bin/" 2>/dev/null || true
cp /usr/local/bin/campus-playerctl "$TMP_DIR/home/" 2>/dev/null || true

# samba + network
cp /etc/samba/smb.conf "$TMP_DIR/" 2>/dev/null || true
cp /etc/netplan/*.yaml "$TMP_DIR/netplan/" 2>/dev/null || true

# promtail config
cp /home/nctk/campus-monitoring/promtail/config.yaml "$TMP_DIR/promtail/" 2>/dev/null || true

# package list
dpkg --get-selections > "$TMP_DIR/packages.txt" 2>/dev/null || true

# hostname + OS info
uname -a > "$TMP_DIR/system-info.txt"
cat /etc/os-release >> "$TMP_DIR/system-info.txt"

# music file list (not the files themselves - those are rsync'd separately)
find /mnt/music/ -type f | sort > "$TMP_DIR/music-files.txt" 2>/dev/null || true

tar -czf /tmp/nctk-config.tar.gz -C /tmp "campus-backup-nctk-$$"
rm -rf "$TMP_DIR"
echo "OK"
NCTK_PACK

    if scp $SSH_OPTS "$NCTK_USER@$NCTK_HOST:/tmp/nctk-config.tar.gz" "$BACKUP_DIR/nctk-config.tar.gz" 2>/dev/null; then
        ssh $SSH_OPTS "$NCTK_USER@$NCTK_HOST" "rm -f /tmp/nctk-config.tar.gz" 2>/dev/null || true
        SIZE=$(du -sh "$BACKUP_DIR/nctk-config.tar.gz" 2>/dev/null | cut -f1)
        ok "nctk-config.tar.gz ($SIZE)"
        STATUS[nctk]="✅ конфиг ($SIZE)"
        SIZES[nctk_config]="$SIZE"
    else
        fail "Не удалось скачать бэкап nctk"
        STATUS[nctk]="❌ ошибка scp"
        ERRORS+=("nctk: ошибка scp config")
        return 1
    fi
}
backup_nctk || true

# ─── 3. Бэкап конфигов VM1 ────────────────────────────────────────────
log "[3/7] Бэкап VM1 (10.70.0.41)..."
backup_vm1() {
    if ! ssh $SSH_OPTS "$VM1_USER@$VM1_HOST" "true" 2>/dev/null; then
        warn "VM1 недоступен, пропускаю"
        STATUS[vm1]="❌ недоступен"
        ERRORS+=("vm1: SSH недоступен")
        return 1
    fi

    ssh $SSH_OPTS "$VM1_USER@$VM1_HOST" bash << 'VM1_PACK'
set -e
TMP_DIR="/tmp/campus-backup-vm1-$$"
mkdir -p "$TMP_DIR/systemd" "$TMP_DIR/home/bin" "$TMP_DIR/netplan" "$TMP_DIR/promtail"

for f in campus-mpv campus-telegram-bot campus-player-watchdog campus-player-watchdog \
          node_exporter promtail; do
    cp /etc/systemd/system/${f}.service "$TMP_DIR/systemd/" 2>/dev/null || true
    cp /etc/systemd/system/${f}.timer   "$TMP_DIR/systemd/" 2>/dev/null || true
done

crontab -l > "$TMP_DIR/crontab.txt" 2>/dev/null || echo "(empty)" > "$TMP_DIR/crontab.txt"

for f in campus-cron-landau-local.sh campus-cron-landau-vm1.sh campus-cron-stop-local.sh \
          campus-playerctl; do
    cp /home/vm1/$f "$TMP_DIR/home/" 2>/dev/null || true
done
cp -r /home/vm1/bin/. "$TMP_DIR/home/bin/" 2>/dev/null || true

cp /etc/netplan/*.yaml "$TMP_DIR/netplan/" 2>/dev/null || true
cp /home/vm1/campus-monitoring/promtail/config.yaml "$TMP_DIR/promtail/" 2>/dev/null || true

dpkg --get-selections > "$TMP_DIR/packages.txt" 2>/dev/null || true
uname -a > "$TMP_DIR/system-info.txt"
cat /etc/os-release >> "$TMP_DIR/system-info.txt"

find /home/vm1/Landau/ -type f | sort > "$TMP_DIR/music-files.txt" 2>/dev/null || true

tar -czf /tmp/vm1-config.tar.gz -C /tmp "campus-backup-vm1-$$"
rm -rf "$TMP_DIR"
echo "OK"
VM1_PACK

    if scp $SSH_OPTS "$VM1_USER@$VM1_HOST:/tmp/vm1-config.tar.gz" "$BACKUP_DIR/vm1-config.tar.gz" 2>/dev/null; then
        ssh $SSH_OPTS "$VM1_USER@$VM1_HOST" "rm -f /tmp/vm1-config.tar.gz" 2>/dev/null || true
        SIZE=$(du -sh "$BACKUP_DIR/vm1-config.tar.gz" 2>/dev/null | cut -f1)
        ok "vm1-config.tar.gz ($SIZE)"
        STATUS[vm1]="✅ конфиг ($SIZE)"
        SIZES[vm1_config]="$SIZE"
    else
        fail "Не удалось скачать бэкап vm1"
        STATUS[vm1]="❌ ошибка scp"
        ERRORS+=("vm1: ошибка scp config")
        return 1
    fi
}
backup_vm1 || true

# ─── 4. rsync музыки NCTK ─────────────────────────────────────────────
log "[4/7] rsync музыки NCTK..."
backup_music_nctk() {
    MUSIC_DST="$BACKUP_BASE/music-nctk"
    mkdir -p "$MUSIC_DST"
    if rsync -az --no-perms --no-owner --no-group --delete --stats \
        -e "ssh $SSH_OPTS" \
        "$NCTK_USER@$NCTK_HOST:$NCTK_MUSIC_PATH" "$MUSIC_DST/" 2>&1 | tail -5; then
        SIZE=$(du -sh "$MUSIC_DST" 2>/dev/null | cut -f1)
        ok "Музыка nctk: $SIZE → $MUSIC_DST"
        STATUS[nctk_music]="✅ $SIZE"
        SIZES[nctk_music]="$SIZE"
    else
        fail "rsync музыки nctk"
        STATUS[nctk_music]="❌ ошибка rsync"
        ERRORS+=("nctk: ошибка rsync музыки")
    fi
}
backup_music_nctk || true

# ─── 5. rsync музыки VM1 ──────────────────────────────────────────────
log "[5/7] rsync музыки VM1..."
backup_music_vm1() {
    MUSIC_DST="$BACKUP_BASE/music-vm1"
    mkdir -p "$MUSIC_DST"
    if rsync -az --no-perms --no-owner --no-group --delete --stats \
        -e "ssh $SSH_OPTS" \
        "$VM1_USER@$VM1_HOST:$VM1_MUSIC_PATH" "$MUSIC_DST/" 2>&1 | tail -5; then
        SIZE=$(du -sh "$MUSIC_DST" 2>/dev/null | cut -f1)
        ok "Музыка vm1: $SIZE → $MUSIC_DST"
        STATUS[vm1_music]="✅ $SIZE"
        SIZES[vm1_music]="$SIZE"
    else
        fail "rsync музыки vm1"
        STATUS[vm1_music]="❌ ошибка rsync"
        ERRORS+=("vm1: ошибка rsync музыки")
    fi
}
backup_music_vm1 || true

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
MUSIC_NCTK_SIZE=$(du -sh "$BACKUP_BASE/music-nctk" 2>/dev/null | cut -f1 || echo "—")
MUSIC_VM1_SIZE=$(du -sh "$BACKUP_BASE/music-vm1" 2>/dev/null | cut -f1 || echo "—")
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
  nctk:        ${STATUS[nctk]:-—}
  vm1:         ${STATUS[vm1]:-—}
  centos:      ${STATUS[centos]:-—}

─── Музыка (rsync, только изменения) ────────────────
  nctk:        ${STATUS[nctk_music]:-—}   ($MUSIC_NCTK_SIZE)
  vm1:         ${STATUS[vm1_music]:-—}   ($MUSIC_VM1_SIZE)

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
• nctk: ${STATUS[nctk]:-—}
• vm1: ${STATUS[vm1]:-—}
• CentOS: ${STATUS[centos]:-—}

*Музыка (rsync):*
• nctk: ${STATUS[nctk_music]:-—}
• vm1: ${STATUS[vm1_music]:-—}

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
