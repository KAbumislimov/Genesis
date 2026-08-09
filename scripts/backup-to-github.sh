#!/bin/bash
# gitkamran: hourly backup — commits and pushes the real (non-anonymized) state of
# campus-infra + helpdesk-ops to the private campus-infra GitHub repo,
# so a fresh machine can be rebuilt with restore.sh at any point.
# Run: bash scripts/backup-to-github.sh   (also wired to an hourly cron job)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$HOME/log/campus-backup-to-github.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$REPO_DIR"

# Синхронизируем личные утилиты (~/.local/bin) в репозиторий, чтобы они
# тоже восстанавливались из GitHub (см. campus-infra/personal-bin)
PERSONAL_BIN="$REPO_DIR/campus-infra/personal-bin"
mkdir -p "$PERSONAL_BIN"
for tool in campus-mon gitkamran; do
    if [[ -f "$HOME/.local/bin/$tool" ]]; then
        cp "$HOME/.local/bin/$tool" "$PERSONAL_BIN/$tool"
    fi
done

# Только campus-infra + helpdesk-ops — НЕ "-A" по всему $HOME/projects,
# чтобы никогда случайно не утащить в бэкап личные файлы (Desktop, Downloads,
# xlsx-отчёты, посторонние git-репозитории вроде nginx-ui и т.п.)
git add campus-infra helpdesk-ops

if git diff --cached --quiet; then
    log "Изменений нет, коммит не нужен"
    exit 0
fi

# Предохранитель: не пушить, если в diff проскочил реальный секрет
if git diff --cached | grep -qE "PASS=[\"']?[A-Za-z0-9]{4,}|BOT_TOKEN=[0-9]{5,}:|gsk_[A-Za-z0-9]{20,}|GEMINI_API_KEY=AQ|BEGIN (OPENSSH|RSA) PRIVATE KEY"; then
    log "СТОП: похоже на секрет в diff — коммит ОТМЕНЁН, разберись руками"
    git reset >/dev/null
    exit 1
fi

git commit -q -m "Auto-backup: $(date '+%Y-%m-%d %H:%M')"
git push origin main >>"$LOG" 2>&1
log "Бэкап выполнен и запушен в GitHub"
