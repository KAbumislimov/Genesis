#!/bin/bash
# Зеркалит campus-infra в публичный (приватный) репозиторий Genesis,
# каждый раз заново обезличивая имена клиентов и вычищая секреты.
# Запуск: bash scripts/sync-to-genesis.sh   (или по cron)
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${GENESIS_DIR:-$HOME/projects/genesis}"
LOG="$HOME/projects/genesis-sync.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if [[ ! -d "$DEST/.git" ]]; then
    log "ОШИБКА: $DEST не найден или не git-репозиторий"
    exit 1
fi

# ── 1. Зеркалирование (кроме секретов/данных и презентационных файлов genesis) ──
rsync -a --delete \
    --exclude-from="$SRC/.gitignore" \
    --exclude='.git' --exclude='data/' \
    --exclude='README.md' --exclude='README.ru.md' --exclude='README.az.md' \
    --exclude='docs/banner.svg' \
    "$SRC/" "$DEST/"

cd "$DEST"

# ── 2. Переименование папок/файлов с реальными именами ──
# Явный список (old -> new), а не паттерн-матчинг — надёжнее и без сюрпризов
# с регистром букв или порядком применения.
RENAMES=(
    "machines/client1:machines/client1"
    "machines/client2:machines/client2"
    "bots/client1:bots/client1"
    "bots/client2:bots/client2"
    "config/cockpit-client2:config/cockpit-client2"
    "docs/SSD-CLIENT1-SETUP.md:docs/SSD-CLIENT1-SETUP.md"
    "promtail-clients/promtail-client1.yaml:promtail-clients/promtail-client1.yaml"
    "promtail-clients/promtail-client2.yaml:promtail-clients/promtail-client2.yaml"
    "scripts/add-test-client2-local-2320.sh:scripts/add-test-client2-local-2320.sh"
    "scripts/check-cron-client2-ON-SERVER.md:scripts/check-cron-client2-ON-SERVER.md"
    "scripts/check-cron-client2.sh:scripts/check-cron-client2.sh"
    "scripts/sync-client1-time.sh:scripts/sync-client1-time.sh"
    "scripts/check-player-on-client2.sh:scripts/check-player-on-client2.sh"
    "scripts/deploy-client2-cron-scripts.sh:scripts/deploy-client2-cron-scripts.sh"
    "scripts/client2-music-debug.sh:scripts/client2-music-debug.sh"
    "scripts/diagnose-client2-music.sh:scripts/diagnose-client2-music.sh"
    "scripts/client2-music-verify.sh:scripts/client2-music-verify.sh"
    "scripts/fix-ssd-permissions-on-client1.sh:scripts/fix-ssd-permissions-on-client1.sh"
    "scripts/fix-client2-campus-mpv-systemd.sh:scripts/fix-client2-campus-mpv-systemd.sh"
    "scripts/fix-client2-campus-mpv-user-service.sh:scripts/fix-client2-campus-mpv-user-service.sh"
    "scripts/fix-client2-music-alsa.sh:scripts/fix-client2-music-alsa.sh"
    "scripts/restore-client1.sh:scripts/restore-client1.sh"
    "scripts/install-crontab-media-local-client2.sh:scripts/install-crontab-media-local-client2.sh"
    "scripts/restore-client2.sh:scripts/restore-client2.sh"
    "scripts/mount-client1-ssd-on-centos.sh:scripts/mount-client1-ssd-on-central.sh"
    "scripts/setup-ssd-on-client1.sh:scripts/setup-ssd-on-client1.sh"
    "scripts/setup-client2-mpv-autostart.sh:scripts/setup-client2-mpv-autostart.sh"
    "scripts/campus-cron-media-local.sh:scripts/campus-cron-media-local.sh"
    "bots/client1/bot_client1.py:bots/client1/bot_client1.py"
    "machines/client1/bin/client1-tg-play.sh:machines/client1/bin/client1-tg-play.sh"
    "machines/client1/bin/client1-tg-stop.sh:machines/client1/bin/client1-tg-stop.sh"
    "machines/client1/bin/client1-tg-vol.sh:machines/client1/bin/client1-tg-vol.sh"
    "machines/client1/scripts/campus-cron-media-local.sh:machines/client1/scripts/campus-cron-media-local.sh"
    "machines/client2/scripts/campus-cron-media-local.sh:machines/client2/scripts/campus-cron-media-local.sh"
    "scripts/systemd/loki-tunnel-client1.service:scripts/systemd/loki-tunnel-client1.service"
    "scripts/systemd/loki-tunnel-client2.service:scripts/systemd/loki-tunnel-client2.service"
    "scripts/systemd/tg-campus-client2.service:scripts/systemd/tg-campus-client2.service"
    "scripts/systemd/tg-campus-client1.service:scripts/systemd/tg-campus-client1.service"
)
for pair in "${RENAMES[@]}"; do
    old="${pair%%:*}"
    new="${pair##*:}"
    if [[ -e "$old" ]]; then
        mkdir -p "$(dirname "$new")"
        mv "$old" "$new"
    fi
done

# Реальные логотипы — не переименовать, а убрать совсем
rm -f webui/static/media.logo.png webui/static/media.logo.t.png \
      webui/static/leg.logo.png webui/static/leg.logo.t.png

# Видимый текст на странице логина, завязанный на реальный бренд
if [[ -f webui/templates/login.html ]]; then
    sed -i \
        -e 's#<div class="logo-name2">the school organization</div>#<div class="logo-name2">Client Organization</div>#' \
        -e 's#<div class="logo-sub2">LEG · Азербайджан</div>#<div class="logo-sub2">Campus Platform</div>#' \
        webui/templates/login.html
fi

# ── 3. Замена текста внутри файлов ──
grep -rIl \
    -e "Media" -e "Клиент 1" -e "Client1" -e "Клиент 2" -e "Client2" -e "Client2" \
    -e "CLIENT1" -e "client1" -e "CLIENT2" -e "client2" -e "leg\.edu\.az" -e "MEDIA" \
    --exclude-dir=.git . 2>/dev/null | while IFS= read -r f; do
    sed -i \
        -e 's/the school organization/the school organization/g' \
        -e 's/k\.abumislimov@leg\.edu\.az/admin@example.edu/g' \
        -e 's/leg\.edu\.az/example.edu/g' \
        -e 's/Клиент 1/Клиент 1/g' \
        -e 's/Клиент 2/Клиент 2/g' \
        -e 's/Client1/Client1/g' \
        -e 's/Client2/Client2/g' \
        -e 's/Client2/Client2/g' \
        -e 's/CLIENT1/CLIENT1/g' \
        -e 's/CLIENT2/CLIENT2/g' \
        -e 's/client1/client1/g' \
        -e 's/client2/client2/g' \
        -e 's/CLIENT1/CLIENT1/g' \
        -e 's/CLIENT2/CLIENT2/g' \
        -e 's/client1/client1/g' \
        -e 's/client2/client2/g' \
        -e 's/Media/Media/g' \
        -e 's/MEDIA/MEDIA/g' \
        -e 's/media/media/g' \
        "$f"
done

# ── 4. Коммит и пуш, только если реально что-то изменилось ──
git add -A

if git diff --cached --quiet; then
    log "Изменений нет, синк не нужен"
    exit 0
fi

# Предохранитель: не пушить, если в diff похоже проскочил реальный секрет
if git diff --cached -- . ':!scripts/sync-to-genesis.sh' | grep -qE "PASS=[\"']?[A-Za-z0-9]{4,}|BOT_TOKEN=[0-9]{5,}:|gsk_[A-Za-z0-9]{20,}|GEMINI_API_KEY=AQ|BEGIN (OPENSSH|RSA) PRIVATE KEY"; then
    log "СТОП: похоже на секрет в diff — коммит и пуш ОТМЕНЕНЫ, разберись руками"
    git reset >/dev/null
    exit 1
fi

git commit -q -m "Auto-sync from campus-infra: $(date '+%Y-%m-%d %H:%M')"
git push origin main >>"$LOG" 2>&1
log "Синк выполнен и запушен"
