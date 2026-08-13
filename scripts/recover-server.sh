#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  RECOVER SERVER — восстановление кампус-инфраструктуры (НЕ всего сервера
#  целиком — Bitwarden/aaPanel/AI-инструменты сюда намеренно не входят,
#  это отдельная история) на чистый CentOS Stream 9 с нуля.
#
#  Запуск на НОВОМ сервере (нужен root/sudo, интернет, Proxmox-бэкап живой):
#      bash recover-server.sh
#  (сам себя нужно сначала скачать — см. ШАГ 0 ниже, скрипт не может
#  запустить сам себя раньше, чем сам появится на машине)
#
#  Что восстанавливает:
#    1. Пакеты: git, rsync, sshpass, Docker CE, nginx (nginx.org repo)
#    2. SSH-ключи (campus_bot, id_tunnel, github, id_ed25519, id_rsa,
#       tg_control) — из бэкапа на Proxmox
#    3. Репозитории: campus-infra (+helpdesk-ops+homelab внутри, монорепо),
#       campus-secrets — через git по восстановленному github-ключу
#    4. .env-файлы campus-infra и helpdesk-ops — восстанавливаются вместе
#       с самими репозиториями из бэкапа на Proxmox (они там есть, т.к.
#       backup копирует ВЕСЬ /home/kamran/projects/<proj>/, включая
#       gitignore'нутые .env — см. homelab/backup/campus-backup.sh)
#    5. /opt/tg-campus-bot/ (сами боты-контроллеры плееров) + их
#       systemd-юниты (tg-campus-client1.service, tg-campus-client2.service)
#    6. nginx-конфиги (campus-audio*.conf)
#    7. Docker compose up для campus-infra + helpdesk-ops
#    8. БД (webui + helpdesk_ops) — из последнего бэкапа
#    9. Media (звонки/гимн, ~800МБ) — из бэкапа на Proxmox
#   10. crontab (недельный бэкап, часовой github-пуш, ежедневный БД-бэкап)
#
#  ЧТО НЕ ВОССТАНАВЛИВАЕТ (осознанно, отдельная задача):
#    - aaPanel и все НЕ-кампусные docker-приложения (Bitwarden, AI-тулзы,
#      GLPI, hertzbeat и т.д.) — см. `docker compose ls` на старом сервере
#    - Cockpit — обычно уже есть в CentOS Stream по умолчанию, если нет —
#      `dnf install cockpit`
#
#  ВАЖНО: сценарий написан и синтаксически проверен, КАЖДЫЙ отдельный шаг
#  (git clone, restore SSH-ключей, docker compose up, БД-restore) реально
#  протестирован в бою в этой же сессии по отдельности — но полный прогон
#  «с абсолютно чистой машины от и до» физически не тестировался (нельзя
#  просто взять и снести продакшн-сервер ради теста). Если что-то пойдёт
#  не по плану — сообщения на каждом шаге подробные, легко понять на чём
#  застряло.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

PROXMOX_HOST="10.20.1.106"
PROXMOX_USER="root"
BACKUP_ROOT="/mnt/campus-backup/centos"
REPO_URL="git@github.com:KAbumislimov/campus-infra.git"
SECRETS_URL="git@github.com:KAbumislimov/campus-secrets.git"
HOME_DIR="/home/kamran"

log()  { echo ""; echo "════ $* ════"; }
ok()   { echo "  ✅ $*"; }
fail() { echo "  ❌ $*" >&2; exit 1; }
ask_pass() { read -r -s -p "$1: " REPLY_PASS; echo ""; echo "$REPLY_PASS"; }

echo "╔══════════════════════════════════════════════════════════╗"
echo "║   RECOVER SERVER — кампус-инфраструктура с нуля           ║"
echo "╚══════════════════════════════════════════════════════════╝"
[[ $EUID -eq 0 ]] || echo "  ⚠️  Запусти под root (sudo) — многие шаги требуют этого."

PROXMOX_PASS="$(ask_pass 'Пароль Proxmox (root@10.20.1.106)')"
[[ -n "$PROXMOX_PASS" ]] || fail "Пароль Proxmox обязателен — без него ничего не восстановить."
prx_ssh()   { sshpass -p "$PROXMOX_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${PROXMOX_USER}@${PROXMOX_HOST}" "$@"; }
prx_rsync() { sshpass -p "$PROXMOX_PASS" rsync -az -e "ssh -o StrictHostKeyChecking=no" "$@"; }

prx_ssh "test -d ${BACKUP_ROOT}" || fail "Бэкап на Proxmox не найден (${BACKUP_ROOT}). Восстанавливать нечего — проверь пароль/хост."
ok "Proxmox-бэкап найден"

# ── 1. Пакеты ──────────────────────────────────────────────────────────
log "ШАГ 1/10 — Пакеты"
dnf install -y -q git rsync sshpass python3 python3-pip >/dev/null
ok "git, rsync, sshpass, python3"

if ! command -v docker >/dev/null 2>&1; then
    dnf install -y -q dnf-plugins-core >/dev/null
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo >/dev/null
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
    systemctl enable --now docker >/dev/null
    ok "Docker CE установлен и запущен"
else
    ok "Docker уже стоит ($(docker --version))"
fi

if ! command -v nginx >/dev/null 2>&1; then
    cat > /etc/yum.repos.d/nginx.repo <<'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/centos/9/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
EOF
    dnf install -y -q nginx >/dev/null
    ok "nginx установлен"
else
    ok "nginx уже стоит"
fi

# ── 2. SSH-ключи ──────────────────────────────────────────────────────
log "ШАГ 2/10 — SSH-ключи из бэкапа"
mkdir -p "$HOME_DIR/.ssh"
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/ssh-keys/" "$HOME_DIR/.ssh/" \
    || fail "Не удалось скачать SSH-ключи с Proxmox"
chmod 700 "$HOME_DIR/.ssh"
chmod 600 "$HOME_DIR"/.ssh/id_* "$HOME_DIR"/.ssh/campus_bot "$HOME_DIR"/.ssh/github "$HOME_DIR"/.ssh/tg_control 2>/dev/null || true
chmod 644 "$HOME_DIR"/.ssh/*.pub "$HOME_DIR/.ssh/authorized_keys" 2>/dev/null || true
chown -R kamran:kamran "$HOME_DIR/.ssh" 2>/dev/null || true
ok "SSH-ключи восстановлены ($(ls "$HOME_DIR/.ssh" | wc -l) файлов)"

# ── 3. Репозитории ────────────────────────────────────────────────────
log "ШАГ 3/10 — Клонирую репозитории (github key)"
export GIT_SSH_COMMAND="ssh -i $HOME_DIR/.ssh/github -o StrictHostKeyChecking=no"
if [[ ! -d "$HOME_DIR/projects/.git" ]]; then
    mkdir -p "$HOME_DIR/projects"
    git clone "$REPO_URL" "$HOME_DIR/projects" || fail "git clone campus-infra не удался — проверь github-ключ"
    ok "campus-infra (+ helpdesk-ops + homelab внутри) склонирован"
else
    ok "campus-infra уже склонирован, пропускаю"
fi
if [[ ! -d "$HOME_DIR/projects/campus-secrets/.git" ]]; then
    git clone "$SECRETS_URL" "$HOME_DIR/projects/campus-secrets" || fail "git clone campus-secrets не удался"
    ok "campus-secrets склонирован"
else
    ok "campus-secrets уже склонирован, пропускаю"
fi
chown -R kamran:kamran "$HOME_DIR/projects"

# ── 4. .env-файлы (из бэкапа поверх git-клона — в git их нет, gitignore) ─
log "ШАГ 4/10 — .env-файлы (campus-infra, helpdesk-ops)"
for proj in campus-infra helpdesk-ops; do
    prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/${proj}/.env" "$HOME_DIR/projects/${proj}/.env" 2>/dev/null \
        && ok "${proj}/.env восстановлен" \
        || echo "  ⚠️  ${proj}/.env не найден в бэкапе — придётся создать вручную"
done

# ── 5. Боты-контроллеры плееров (/opt/tg-campus-bot) ─────────────────────
log "ШАГ 5/10 — Telegram-боты (/opt/tg-campus-bot)"
mkdir -p /opt/tg-campus-bot
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/tg-campus-bot/" /opt/tg-campus-bot/ \
    || fail "Не удалось восстановить /opt/tg-campus-bot"
ok "/opt/tg-campus-bot восстановлен ($(du -sh /opt/tg-campus-bot | cut -f1))"

mkdir -p /tmp/.systemd-units-restore
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/systemd-units/" /tmp/.systemd-units-restore/ \
    || fail "Не удалось скачать systemd-юниты ботов"
cp -f /tmp/.systemd-units-restore/*.service /etc/systemd/system/
rm -rf /tmp/.systemd-units-restore
systemctl daemon-reload
for svc in tg-campus-client1.service tg-campus-client2.service; do
    if [[ -f "/etc/systemd/system/$svc" ]]; then
        systemctl enable --now "$svc" >/dev/null 2>&1 && ok "$svc запущен" || echo "  ⚠️  $svc не запустился — проверь руками"
    fi
done

# ── 6. nginx-конфиги ───────────────────────────────────────────────────
log "ШАГ 6/10 — nginx-конфиги"
mkdir -p /etc/nginx/conf.d
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/nginx-conf/" /etc/nginx/conf.d/ \
    && ok "nginx-конфиги восстановлены" \
    || echo "  ⚠️  nginx-конфиги не восстановились — проверь руками"
nginx -t 2>&1 && systemctl enable --now nginx >/dev/null 2>&1 && ok "nginx запущен" \
    || echo "  ⚠️  nginx -t упал — конфиг требует ручной правки (SSL-сертификаты и т.п.) прежде чем стартовать"

# ── 7. Media (звонки/гимн) — до docker compose up, чтобы сразу было на месте
log "ШАГ 7/10 — Media (звонки/гимн)"
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/media-music/" "$HOME_DIR/Media/" \
    && ok "Media восстановлен ($(du -sh "$HOME_DIR/Media" 2>/dev/null | cut -f1))" \
    || echo "  ⚠️  Media не восстановился — проверь путь бэкапа руками"
chown -R kamran:kamran "$HOME_DIR/Media" 2>/dev/null || true

# ── 8. Docker compose up ──────────────────────────────────────────────
log "ШАГ 8/10 — Docker compose (campus-infra + helpdesk-ops)"
# ВАЖНО: docker-compose.yaml также ОПИСЫВАЕТ сервисы tg-campus-bot и
# tg-campus-client2, но они никогда реально не разворачивались как
# контейнеры — те же боты уже работают как systemd-сервисы (см. шаг 5),
# читая /opt/tg-campus-bot/*.env напрямую. Если поднять их ЕЩЁ и в docker —
# получится два процесса с одним и тем же BOT_TOKEN, Telegram начнёт
# отдавать 409 Conflict обоим. Поэтому запускаем явным списком, без них.
(cd "$HOME_DIR/projects/campus-infra" && docker compose up -d \
    loki grafana promtail prometheus node-exporter campus-recovery campus-webui campus-watchdog cockpit-proxy) \
    && ok "campus-infra контейнеры подняты (без tg-campus-bot/client2 — те живут в systemd)" \
    || echo "  ⚠️  campus-infra docker compose up упал — смотри docker compose logs"
(cd "$HOME_DIR/projects/helpdesk-ops" && docker compose up -d) \
    && ok "helpdesk-ops контейнер поднят" \
    || echo "  ⚠️  helpdesk-ops docker compose up упал — смотри docker compose logs"

# ── 9. БД (поверх свежесозданных пустых, из последнего бэкапа) ──────────
log "ШАГ 9/10 — Базы данных из бэкапа"
sleep 5  # дать контейнерам создать свежие (пустые) БД перед перезаписью
mkdir -p /tmp/.db-restore
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/webui-data/" /tmp/.db-restore/webui-data/ 2>/dev/null || true
prx_rsync "${PROXMOX_USER}@${PROXMOX_HOST}:${BACKUP_ROOT}/helpdesk-ops/data/" /tmp/.db-restore/helpdesk-ops-data/ 2>/dev/null || true
if [[ -d /tmp/.db-restore/webui-data ]]; then
    (cd "$HOME_DIR/projects/campus-infra" && docker compose stop campus-webui) 2>/dev/null || true
    rsync -a /tmp/.db-restore/webui-data/ "$HOME_DIR/projects/campus-infra/data/"
    (cd "$HOME_DIR/projects/campus-infra" && docker compose start campus-webui) 2>/dev/null || true
    ok "webui БД восстановлена"
fi
if [[ -d /tmp/.db-restore/helpdesk-ops-data ]]; then
    (cd "$HOME_DIR/projects/helpdesk-ops" && docker compose stop helpdesk-ops) 2>/dev/null || true
    rsync -a /tmp/.db-restore/helpdesk-ops-data/ "$HOME_DIR/projects/helpdesk-ops/data/"
    (cd "$HOME_DIR/projects/helpdesk-ops" && docker compose start helpdesk-ops) 2>/dev/null || true
    ok "helpdesk-ops БД восстановлена"
fi
rm -rf /tmp/.db-restore

# ── 10. crontab ────────────────────────────────────────────────────────
log "ШАГ 10/10 — crontab"
CRON_TMP=$(mktemp)
crontab -u kamran -l 2>/dev/null > "$CRON_TMP" || true
if ! grep -q "campus-backup.sh" "$CRON_TMP" 2>/dev/null; then
    cat >> "$CRON_TMP" <<EOF
0 2 * * 0 $HOME_DIR/projects/homelab/backup/campus-backup.sh >> $HOME_DIR/log/campus-backup-\$(date +\%Y-\%m-\%d).log 2>&1
0 3 * * * $HOME_DIR/projects/campus-infra/scripts/backup-data.sh >> $HOME_DIR/log/backup-data.log 2>&1
0 * * * * $HOME_DIR/projects/campus-infra/scripts/backup-to-github.sh >> $HOME_DIR/log/backup-to-github.log 2>&1
EOF
    mkdir -p "$HOME_DIR/log"
    chown kamran:kamran "$HOME_DIR/log"
    crontab -u kamran "$CRON_TMP"
    ok "crontab восстановлен"
else
    ok "crontab уже содержит бэкапы, не трогаю"
fi
rm -f "$CRON_TMP"

# ── Итог ──────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ВОССТАНОВЛЕНИЕ ЗАВЕРШЕНО                                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Проверь:"
echo "    docker compose -f $HOME_DIR/projects/campus-infra/docker-compose.yaml ps"
echo "    docker compose -f $HOME_DIR/projects/helpdesk-ops/docker-compose.yml ps"
echo "    curl -k https://localhost:8090/  (campus-webui)"
echo "    curl -k https://localhost:8094/  (helpdesk-ops)"
echo "    systemctl status tg-campus-client1 tg-campus-client2"
echo ""
echo "  ⚠️  Отдельно, руками (не автоматизировано):"
echo "    - Cockpit, если не установлен: dnf install cockpit && systemctl enable --now cockpit.socket"
echo "    - Kamran Music (33ГБ) — библиотека для команды /play N, НЕ в бэкапе,"
echo "      восстанови из /home/kamran/'Kamran Music' если есть отдельная копия"
echo "    - Bitwarden, aaPanel, AI-инструменты и прочие НЕ-кампусные docker-приложения"
echo "      (см. шапку этого скрипта) — сюда сознательно не входят"
