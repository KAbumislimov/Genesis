#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  CAMPUS WEEKLY BACKUP — Landau Education Group
#  Запуск: каждое воскресенье в 02:00 (cron на главном сервере)
#  Хранилище: root@10.20.1.106:/mnt/campus-backup
#  Логика: новый бэкап → удаляет предыдущий (хранится 1 поколение)
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a

PROXMOX_HOST="10.20.1.106"
PROXMOX_USER="root"
PROXMOX_PASS="${PROXMOX_PASS:?Укажите пароль: PROXMOX_PASS=... bash scripts/campus-backup.sh (или добавьте в .env)}"
BACKUP_ROOT="/mnt/campus-backup"
LOCAL_TMP="/tmp/campus-backup-staging"
DATE=$(date +%Y-%m-%d)
LOG="/var/log/campus-backup.log"
SSHPASS="sshpass -p ${PROXMOX_PASS}"

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
fail() { log "❌ ОШИБКА: $*"; }
ok()   { log "✅ $*"; }

# ── SSH/RSYNC хелперы ─────────────────────────────────────────────────
proxmox_ssh() {
    $SSHPASS ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "${PROXMOX_USER}@${PROXMOX_HOST}" "$@"
}
proxmox_rsync() {
    $SSHPASS rsync -az --delete --stats \
        -e "ssh -o StrictHostKeyChecking=no" \
        "$@"
}

# ── Ротация: оставляем только последний бэкап ─────────────────────────
rotate() {
    local target="$1"  # e.g. campus-server
    log "Ротация $target — удаляю старые..."
    proxmox_ssh "
        cd ${BACKUP_ROOT}
        ls -d ${target}_* 2>/dev/null | sort | head -n -1 | while read d; do
            rm -rf \"\$d\" && echo \"  Удалён: \$d\"
        done
    " 2>>"$LOG" || true
}

# ── Создаём директорию для сегодняшнего бэкапа ───────────────────────
make_dir() {
    local name="${DATE}_$1"
    proxmox_ssh "mkdir -p ${BACKUP_ROOT}/${name}" 2>>"$LOG"
    echo "${BACKUP_ROOT}/${name}"
}

log "══════════════════════════════════════"
log "CAMPUS BACKUP START — ${DATE}"
log "══════════════════════════════════════"

# ── 1. ГЛАВНЫЙ СЕРВЕР (campus-infra данные) ───────────────────────────
log "▶ Бэкап: campus-server (10.10.4.120)"
rotate "campus-server"
DEST=$(make_dir "campus-server")

# WebUI данные (БД, обои, аватары, объявления)
proxmox_rsync \
    /home/kamran/projects/campus-infra/data/ \
    "${PROXMOX_USER}@${PROXMOX_HOST}:${DEST}/webui-data/" \
    && ok "campus-server → webui-data" \
    || fail "campus-server → webui-data"

# Конфиги и скрипты инфраструктуры (без .git и node_modules)
proxmox_rsync \
    --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
    /home/kamran/projects/campus-infra/ \
    "${PROXMOX_USER}@${PROXMOX_HOST}:${DEST}/campus-infra-configs/" \
    && ok "campus-server → campus-infra-configs" \
    || fail "campus-server → campus-infra-configs"

# Секреты (только структура без данных — сами секреты в campus-secrets)
proxmox_rsync \
    --exclude='.git' \
    /home/kamran/projects/campus-secrets/ \
    "${PROXMOX_USER}@${PROXMOX_HOST}:${DEST}/campus-secrets/" \
    && ok "campus-server → campus-secrets" \
    || fail "campus-server → campus-secrets"

# ── 2. НАРИМАНОВ (nctk) ───────────────────────────────────────────────
log "▶ Бэкап: nctk (10.20.0.41)"
rotate "nctk"
DEST=$(make_dir "nctk")

proxmox_rsync \
    --exclude='.cache' --exclude='.local' --exclude='__pycache__' \
    -e "ssh -J ${PROXMOX_USER}@${PROXMOX_HOST} -o StrictHostKeyChecking=no" \
    nctk:/home/nctk/ \
    "${PROXMOX_USER}@${PROXMOX_HOST}:${DEST}/home-nctk/" \
    2>>"$LOG" \
    && ok "nctk → home-nctk" \
    || {
        # fallback: через tar на nctk → передаём на Proxmox
        log "  Fallback: tar через nctk..."
        ssh -o ConnectTimeout=10 nctk \
            "tar czf - --exclude='.cache' --exclude='.local' /home/nctk/ 2>/dev/null" \
        | $SSHPASS ssh -o StrictHostKeyChecking=no "${PROXMOX_USER}@${PROXMOX_HOST}" \
            "mkdir -p ${DEST} && cat > ${DEST}/home-nctk.tar.gz" \
        && ok "nctk → home-nctk.tar.gz (fallback)" \
        || fail "nctk → home-nctk FAILED"
    }

# Systemd сервисы nctk
ssh -o ConnectTimeout=10 nctk \
    "tar czf - /etc/systemd/system/campus-*.service /etc/systemd/system/campus-*.timer 2>/dev/null" \
| $SSHPASS ssh -o StrictHostKeyChecking=no "${PROXMOX_USER}@${PROXMOX_HOST}" \
    "cat > ${DEST}/systemd-services.tar.gz" \
&& ok "nctk → systemd-services" \
|| fail "nctk → systemd-services"

# ── 3. ГЯНДЖЛИК (vm1) ────────────────────────────────────────────────
log "▶ Бэкап: vm1 (10.70.0.41)"
rotate "vm1"
DEST=$(make_dir "vm1")

ssh -o ConnectTimeout=10 vm1 \
    "tar czf - --exclude='.cache' --exclude='.local' --exclude='Landau' /home/vm1/ 2>/dev/null" \
| $SSHPASS ssh -o StrictHostKeyChecking=no "${PROXMOX_USER}@${PROXMOX_HOST}" \
    "mkdir -p ${DEST} && cat > ${DEST}/home-vm1.tar.gz" \
&& ok "vm1 → home-vm1.tar.gz" \
|| fail "vm1 → home-vm1"

# /opt/campus (kiosk скрипты)
ssh -o ConnectTimeout=10 vm1 \
    "tar czf - /opt/campus/ /etc/systemd/system/campus-*.service 2>/dev/null" \
| $SSHPASS ssh -o StrictHostKeyChecking=no "${PROXMOX_USER}@${PROXMOX_HOST}" \
    "cat > ${DEST}/opt-campus.tar.gz" \
&& ok "vm1 → opt-campus.tar.gz" \
|| fail "vm1 → opt-campus"

# ── 4. ИТОГ ──────────────────────────────────────────────────────────
log "▶ Содержимое хранилища Proxmox:"
proxmox_ssh "du -sh ${BACKUP_ROOT}/*/ 2>/dev/null | sort -rh" 2>>"$LOG" | tee -a "$LOG"

log "══════════════════════════════════════"
log "CAMPUS BACKUP DONE — ${DATE}"
log "══════════════════════════════════════"

# ── 5. TELEGRAM УВЕДОМЛЕНИЕ ──────────────────────────────────────────
python3 /home/kamran/projects/campus-infra/scripts/backup-notify.py "$LOG" \
    && log "📱 Telegram уведомление отправлено" \
    || log "⚠️  Telegram уведомление не удалось отправить"
