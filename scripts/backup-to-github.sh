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

# Перед каждым коммитом: (1) выгрузить «живое состояние» системы — права ролей, настройки, машины,
# расписание, crontab и ЗАШИФРОВАННЫЙ снимок БД — в campus-infra/state/, (2) дописать в docs/journal/
# что именно менялось. Так на новом железе всё (а не только код) восстанавливается командой из GitHub.
# Обе программы только читают БД и никогда не роняют бэкап (|| true).
python3 "$REPO_DIR/campus-infra/scripts/export_state.py" >>"$LOG" 2>&1 || true
python3 "$REPO_DIR/campus-infra/scripts/update_journal.py" >>"$LOG" 2>&1 || true

# Только campus-infra + helpdesk-ops + ops-journal — НЕ "-A" по всему
# $HOME/projects, чтобы никогда случайно не утащить в бэкап личные файлы
# (Desktop, Downloads, xlsx-отчёты, посторонние git-репозитории вроде
# nginx-ui и т.п.). ops-journal/raw/ гитигнорится внутри самого ops-journal —
# сюда попадает только уже очищенный (sanitize.py) ops-journal/clean/.
git add campus-infra helpdesk-ops ops-journal homelab/backup   # homelab/backup — campus-backup.sh (недельный бэкап на Proxmox)
# README.md и CLAUDE.md в корне репозитория (уже отслеживаются git, но лежат ВЫШЕ REPO_DIR) —
# правки от руки раньше требовали отдельного commit/push; теперь идут в тот же авто-бэкап (2026-09-26).
git -C "$REPO_DIR/.." add README.md CLAUDE.md 2>>"$LOG" || true

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

# Предохранитель: реальный IP (10.x.x.x) в публичном README/docs — их писали руками, там должны
# быть только плейсхолдеры <IP сервера> и т.п. (см. campus-secrets/server/infra-values.md, 2026-09-26).
if git diff --cached -- README.md 'campus-infra/docs/*.md' campus-infra/RESTORE.md campus-infra/README.md \
     | grep -E '^\+' | grep -qE '(^|[^0-9.])10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)'; then
    log "СТОП: похоже на реальный IP в публичном README/docs — коммит ОТМЕНЁН, разберись руками"
    git reset >/dev/null
    exit 1
fi

git commit -q -m "Auto-backup: $(date '+%Y-%m-%d %H:%M')"
git push origin main >>"$LOG" 2>&1
log "Бэкап выполнен и запушен в GitHub"
