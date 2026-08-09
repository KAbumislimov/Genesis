#!/usr/bin/env bash
# Бэкап данных webui, helpdesk (старый прототип) и helpdesk-ops в campus-backups
# Запускать по cron: 0 3 * * * bash ~/projects/campus-infra/scripts/backup-data.sh

REPO_DIR="$HOME/projects/campus-infra"
HELPDESK_OPS_DIR="$HOME/projects/helpdesk-ops"
BACKUP_DIR="${CAMPUS_BACKUP_DIR:-$HOME/campus-backups}"
DATE=$(date +%Y-%m-%d)
DEST="$BACKUP_DIR/db/$DATE"

mkdir -p "$DEST"

# webui.db — пользователи, тонкие клиенты, настройки
if [[ -f "$REPO_DIR/data/webui/webui.db" ]]; then
    cp "$REPO_DIR/data/webui/webui.db" "$DEST/webui.db"
    echo "[$(date +%H:%M)] webui.db → $DEST/webui.db"
fi

# helpdesk.db (старый прототип landau-helpdesk, порт 8091)
if [[ -f "$REPO_DIR/data/helpdesk/helpdesk.db" ]]; then
    cp "$REPO_DIR/data/helpdesk/helpdesk.db" "$DEST/helpdesk.db"
    echo "[$(date +%H:%M)] helpdesk.db → $DEST/helpdesk.db"
fi

# helpdesk_ops.db + вложения (текущий Helpdesk Ops, порт 8094)
if [[ -f "$HELPDESK_OPS_DIR/data/helpdesk_ops.db" ]]; then
    cp "$HELPDESK_OPS_DIR/data/helpdesk_ops.db" "$DEST/helpdesk_ops.db"
    echo "[$(date +%H:%M)] helpdesk_ops.db → $DEST/helpdesk_ops.db"
fi
if [[ -d "$HELPDESK_OPS_DIR/data/uploads" ]]; then
    tar czf "$DEST/helpdesk_ops_uploads.tar.gz" -C "$HELPDESK_OPS_DIR/data" uploads
    echo "[$(date +%H:%M)] helpdesk-ops uploads → $DEST/helpdesk_ops_uploads.tar.gz"
fi

# Оставляем только последние 30 дней
find "$BACKUP_DIR/db" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
echo "[$(date +%H:%M)] Бэкап завершён: $DEST"
