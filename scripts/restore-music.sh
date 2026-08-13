#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  RESTORE MUSIC/BELLS — копирует мастер-копию Media (звонки/гимн/
#  плейлисты) на кампус-машину. Источник, по приоритету:
#    1. Локальная мастер-копия на сервере (/home/kamran/Media) — обычный путь
#    2. Резерв на Proxmox (${BACKUP_ROOT}/centos/media-music/) — если вдруг
#       локальной копии нет (см. homelab/backup/campus-backup.sh, шаг
#       "centos → media-music", бэкапится туда еженедельно с 2026-08-13)
#
#  Запуск (с центрального CentOS-сервера):
#      bash scripts/restore-music.sh client1
#      bash scripts/restore-music.sh client2
#  Предполагает, что SSH-доступ к кампус-машине уже настроен
#  (см. scripts/setup-recovery-ssh-keys.sh — шаг ПЕРЕД этим).
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a

CAMPUS="${1:-}"
if [[ "$CAMPUS" != "client1" && "$CAMPUS" != "client2" ]]; then
    echo "Использование: bash scripts/restore-music.sh client1|client2" >&2
    exit 1
fi

MASTER_SRC="/home/kamran/Media"
CAMPUS_KEY="${CAMPUS_KEY:-/home/kamran/.ssh/campus_bot}"
PROXMOX_HOST="10.20.1.106"
PROXMOX_USER="root"
PROXMOX_KEY="${PROXMOX_KEY:-/home/kamran/.ssh/id_ed25519}"

log()  { echo "[restore-music:${CAMPUS}] $*"; }
fail() { echo "[restore-music:${CAMPUS}] ❌ $*" >&2; exit 1; }

if [[ -d "$MASTER_SRC" ]]; then
    SRC_SIZE=$(du -sh "$MASTER_SRC" | cut -f1)
    log "Мастер-копия найдена локально: $MASTER_SRC ($SRC_SIZE)"
else
    log "Локальной копии нет ($MASTER_SRC) — тяну резерв с Proxmox..."
    ssh -i "$PROXMOX_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${PROXMOX_USER}@${PROXMOX_HOST}" \
        "test -d /mnt/campus-backup/centos/media-music" \
        || fail "Резерва на Proxmox тоже нет (/mnt/campus-backup/centos/media-music) — данных нет нигде"
    mkdir -p "$MASTER_SRC"
    rsync -az -e "ssh -i $PROXMOX_KEY -o StrictHostKeyChecking=no" \
        "${PROXMOX_USER}@${PROXMOX_HOST}:/mnt/campus-backup/centos/media-music/" "$MASTER_SRC/" \
        || fail "Не удалось скачать резерв с Proxmox"
    SRC_SIZE=$(du -sh "$MASTER_SRC" | cut -f1)
    log "Скачано с Proxmox: $MASTER_SRC ($SRC_SIZE)"
fi

# ── 1. Проверить SSH-доступ к кампус-машине ─────────────────────────────
log "Проверяю SSH-доступ к $CAMPUS..."
ssh -i "$CAMPUS_KEY" -o ConnectTimeout=8 -o StrictHostKeyChecking=no -o BatchMode=yes "$CAMPUS" "echo ok" >/dev/null 2>&1 \
    || fail "Нет SSH-доступа к $CAMPUS (алиас из ~/.ssh/config). Сначала: bash scripts/setup-recovery-ssh-keys.sh"

# ── 2. Определить целевой путь на кампус-машине ──────────────────────────
if [[ "$CAMPUS" == "client1" ]]; then
    DEST="/mnt/music/Media"
    ssh -i "$CAMPUS_KEY" "$CAMPUS" "sudo mkdir -p /mnt/music && sudo chown \$(whoami):\$(whoami) /mnt/music" < /dev/null \
        || fail "Не удалось подготовить /mnt/music на client1"
else
    DEST="/home/client2/Media"
fi

# ── 3. Синхронизировать (rsync поверх ssh, с ключом campus_bot) ─────────
log "Синхронизирую $MASTER_SRC → ${CAMPUS}:${DEST} ..."
rsync -az --info=progress2 \
    -e "ssh -i $CAMPUS_KEY -o StrictHostKeyChecking=no" \
    "$MASTER_SRC/" "${CAMPUS}:${DEST}/" \
    || fail "rsync не удался"

# ── 4. Проверка результата ──────────────────────────────────────────────
log "Проверяю результат..."
RESULT=$(ssh -i "$CAMPUS_KEY" "$CAMPUS" "du -sh '$DEST' 2>/dev/null; find '$DEST' -type f | wc -l") \
    || fail "Не удалось проверить $DEST на $CAMPUS"
echo "$RESULT"
FILE_COUNT=$(echo "$RESULT" | tail -1)
[[ "$FILE_COUNT" -gt 0 ]] 2>/dev/null || fail "После синхронизации 0 файлов — что-то не так"

log "✅ Готово: музыка/звонки для $CAMPUS восстановлены из мастер-копии ($SRC_SIZE, $FILE_COUNT файлов)"
