#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  RECOVER CAMPUS MACHINE — полное восстановление client1/client2 ОДНОЙ командой,
#  после того как на новую машину руками поставили Ubuntu 22.04 Server
#  (это единственный шаг, который нельзя автоматизировать — нужны руки
#  и флешка).
#
#  Запуск (с центрального CentOS-сервера):
#      bash scripts/recover-campus-machine.sh client1 10.20.1.50 SomeTempPass
#      bash scripts/recover-campus-machine.sh client2  10.20.1.103 pas123123
#
#  Делает всё за один проход:
#    1. Проверка SSH/sudo доступа по временному паролю
#    2. Временный passwordless sudo на кампус-машине (снимается в конце)
#    3. SSH-ключи на кампус-машину + обновление алиаса ~/.ssh/config
#       (сделано ДО install.sh специально — нужно для шага 4)
#    4. install.sh (пакеты, плеер, watchdog, cron-расписание звонков,
#       audio-analyzer) И restore-music.sh (музыка/звонки) — ПАРАЛЛЕЛЬНО,
#       фоновыми задачами с раздельным логом и проверкой кода возврата
#    5. Токен бота из campus-secrets — С ПРОВЕРКОЙ, что он реально рабочий
#       (запускает локальный бот только если Telegram API его принял)
#    6. Обновление CLIENT_HOST в конфиге серверного control-бота
#       (тот, что даёт кнопки Громче/Тише/Стоп в Telegram-группе) +
#       его перезапуск (нужен once-выданный scoped sudo, см. README ниже)
#
#  Требует один раз заранее (см. docs/DISASTER-RECOVERY.md):
#      echo "kamran ALL=(ALL) NOPASSWD: \
#        /usr/bin/systemctl restart tg-campus-client1.service, \
#        /usr/bin/systemctl restart tg-campus-client2.service" \
#        | sudo tee /etc/sudoers.d/90-campus-bot-restart
#  Без этого шаг 6 просто попросит перезапустить руками — всё остальное
#  всё равно отработает.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/.env" ]] && set -a && source "$REPO/.env" && set +a

CAMPUS="${1:-}"
TEMP_IP="${2:-}"
TEMP_PASS="${3:-}"

if [[ "$CAMPUS" != "client1" && "$CAMPUS" != "client2" ]] || [[ -z "$TEMP_IP" ]] || [[ -z "$TEMP_PASS" ]]; then
    echo "Использование: bash scripts/recover-campus-machine.sh client1|client2 <ip> <временный_пароль>" >&2
    exit 1
fi

# ── Конфигурация по кампусам ──────────────────────────────────────────────
if [[ "$CAMPUS" == "client1" ]]; then
    CAMPUS_USER="client1"
    CAMPUS_HOME="/home/client1"
    SERVER_BOT_SERVICE="tg-campus-client1.service"
    SERVER_BOT_ENV="/opt/tg-campus-bot/client1.env"
else
    CAMPUS_USER="client2"
    CAMPUS_HOME="/home/client2"
    SERVER_BOT_SERVICE="tg-campus-client2.service"
    SERVER_BOT_ENV="/opt/tg-campus-bot/client2.env"
fi

INSTALL_SRC="$REPO/machines/$CAMPUS"
SECRETS_BOT_CONFIG="$HOME/projects/campus-secrets/$CAMPUS/telegram-bot.config.env"
CAMPUS_KEY="${CAMPUS_KEY:-$HOME/.ssh/campus_bot}"
ALIAS_KEY="${ALIAS_KEY:-$HOME/.ssh/id_tunnel}"
SUDOERS_MARKER="/etc/sudoers.d/90-${CAMPUS}-install-temp"
SSH_CONFIG="$HOME/.ssh/config"

log()  { echo "[recover:${CAMPUS}] ▶ $*"; }
ok()   { echo "[recover:${CAMPUS}] ✅ $*"; }
warn() { echo "[recover:${CAMPUS}] ⚠️  $*"; }
fail() { echo "[recover:${CAMPUS}] ❌ $*" >&2; exit 1; }

# Reuse one SSH connection across all the temp-password calls below instead
# of renegotiating a fresh handshake every time — noticeably faster on a
# slow/high-latency link, and simply not used at all if the first `sp` call
# fails (ControlMaster=auto degrades to a normal one-off connection).
SSH_CTL_PATH="/tmp/.ssh-cm-recover-${CAMPUS}-%r@%h:%p"
SSH_CM_OPTS=(-o ControlMaster=auto -o ControlPersist=120s -o "ControlPath=$SSH_CTL_PATH")
sp() { sshpass -p "$TEMP_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${SSH_CM_OPTS[@]}" "${CAMPUS_USER}@${TEMP_IP}" "$@"; }
sp_scp_to() { sshpass -p "$TEMP_PASS" scp -o StrictHostKeyChecking=no "${SSH_CM_OPTS[@]}" "$1" "${CAMPUS_USER}@${TEMP_IP}:$2"; }

# ── 1. Проверка доступа ───────────────────────────────────────────────────
log "Проверяю SSH/sudo доступ к $TEMP_IP..."
sp "echo ok" >/dev/null 2>&1 || fail "Нет SSH-доступа. Проверь IP/пароль."
sp "echo '$TEMP_PASS' | sudo -S true" >/dev/null 2>&1 || fail "Пароль не подходит для sudo на $CAMPUS_USER."
ok "SSH/sudo доступ подтверждён"

# ── 2. Временный passwordless sudo (снимается в конце скрипта) ───────────
log "Включаю временный NOPASSWD sudo на время установки..."
sp "echo '$TEMP_PASS' | sudo -S bash -c 'echo \"$CAMPUS_USER ALL=(ALL) NOPASSWD:ALL\" > $SUDOERS_MARKER && chmod 440 $SUDOERS_MARKER && visudo -c'" >/dev/null \
    || fail "Не удалось настроить временный sudoers"
ok "Временный sudo включён"

# ── 3. SSH-ключи на кампус-машину (для алиаса и для control-бота) ────────
# Перенесено раньше install.sh специально: restore-music.sh (шаг 5) требует
# уже рабочий SSH-алиас с ключом, а не временный пароль — значит, ключ и
# алиас должны быть готовы ДО того, как мы запустим install.sh и
# restore-music.sh параллельно.
log "Добавляю SSH-ключи на машину..."
for pubkey in "${ALIAS_KEY}.pub" "${CAMPUS_KEY}.pub"; do
    [[ -f "$pubkey" ]] || continue
    PK=$(cat "$pubkey")
    sp "mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qF '$PK' ~/.ssh/authorized_keys 2>/dev/null || echo '$PK' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys"
done
ok "SSH-ключи добавлены"

# ── 4. Обновляем SSH-алиас ~/.ssh/config → новый IP ───────────────────────
log "Обновляю SSH-алиас '$CAMPUS' → $TEMP_IP..."
if grep -q "^Host ${CAMPUS}\$" "$SSH_CONFIG" 2>/dev/null; then
    python3 - "$SSH_CONFIG" "$CAMPUS" "$TEMP_IP" <<'PYEOF'
import sys, re
path, campus, ip = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read()
pattern = re.compile(r'(Host %s\n(?:.*\n)*?    HostName )\S+' % re.escape(campus))
new_text, n = pattern.subn(r'\g<1>' + ip, text, count=1)
if n:
    open(path, 'w').write(new_text)
PYEOF
else
    cat >> "$SSH_CONFIG" <<EOF

Host $CAMPUS
    HostName $TEMP_IP
    User $CAMPUS_USER
    IdentityFile $ALIAS_KEY
    IdentitiesOnly yes
EOF
fi
ssh -o BatchMode=yes -o ConnectTimeout=8 "$CAMPUS" "echo ok" >/dev/null 2>&1 \
    || fail "SSH-алиас '$CAMPUS' не заработал после обновления — проверь ~/.ssh/config"
ok "ssh $CAMPUS теперь работает без пароля"

# ── 5. install.sh и музыка — ПАРАЛЛЕЛЬНО ──────────────────────────────────
# Не пересекаются: install.sh трогает пакеты/systemd/cron, restore-music.sh
# трогает только Media/-каталог с аудио. Оба идут в фоне, дальше ждём
# каждый отдельно и проверяем реальный код возврата — set -e фон сам по
# себе не ловит, поэтому проверка через wait обязательна.
log "Копирую установочные файлы..."
sshpass -p "$TEMP_PASS" rsync -az --exclude='.git' -e "ssh -o StrictHostKeyChecking=no" \
    "$INSTALL_SRC/" "${CAMPUS_USER}@${TEMP_IP}:${CAMPUS_HOME}/${CAMPUS}-install/" \
    || fail "rsync установочных файлов не удался"
ok "Файлы скопированы"

INSTALL_LOG=$(mktemp)
MUSIC_LOG=$(mktemp)

log "Запускаю install.sh и restore-music.sh параллельно (install: пакеты+плеер+cron+watchdog; музыка: ~800МБ)..."
( sp "cd ${CAMPUS_HOME}/${CAMPUS}-install && bash install.sh" ) >"$INSTALL_LOG" 2>&1 &
INSTALL_PID=$!
( bash "$REPO/scripts/restore-music.sh" "$CAMPUS" ) >"$MUSIC_LOG" 2>&1 &
MUSIC_PID=$!

INSTALL_RC=0
wait "$INSTALL_PID" || INSTALL_RC=$?
sed 's/^/    [install] /' "$INSTALL_LOG"
if [[ "$INSTALL_RC" -ne 0 ]]; then
    kill "$MUSIC_PID" 2>/dev/null || true
    wait "$MUSIC_PID" 2>/dev/null || true
    rm -f "$INSTALL_LOG" "$MUSIC_LOG"
    fail "install.sh завершился с ошибкой (код $INSTALL_RC) — смотри вывод выше"
fi
ok "install.sh выполнен"

MUSIC_RC=0
wait "$MUSIC_PID" || MUSIC_RC=$?
sed 's/^/    [music]   /' "$MUSIC_LOG"
rm -f "$INSTALL_LOG" "$MUSIC_LOG"
if [[ "$MUSIC_RC" -ne 0 ]]; then
    fail "restore-music.sh завершился с ошибкой (код $MUSIC_RC) — смотри вывод выше"
fi
ok "Музыка/звонки восстановлены"

# ── 6. Бот-токен из campus-secrets — с проверкой валидности ──────────────
if [[ -f "$SECRETS_BOT_CONFIG" ]]; then
    log "Проверяю токен локального бота из campus-secrets..."
    BOT_TOKEN=$(grep '^BOT_TOKEN=' "$SECRETS_BOT_CONFIG" | cut -d= -f2)
    if [[ -n "$BOT_TOKEN" ]] && curl -sf --max-time 10 "https://api.telegram.org/bot${BOT_TOKEN}/getMe" | grep -q '"ok":true'; then
        sp_scp_to "$SECRETS_BOT_CONFIG" "${CAMPUS_HOME}/telegram-campus-bot/config.env"
        sp "sudo systemctl enable --now campus-telegram-bot" >/dev/null 2>&1
        ok "Токен рабочий — локальный бот запущен"
    else
        warn "Токен в campus-secrets НЕДЕЙСТВИТЕЛЕН (не прошёл проверку Telegram API) — локальный бот не запущен. Нужен свежий токен от @BotFather → campus-secrets/$CAMPUS/telegram-bot.config.env"
    fi
else
    warn "Нет файла $SECRETS_BOT_CONFIG — локальный бот не настроен"
fi

# ── 7. Серверный control-бот: новый CLIENT_HOST + рестарт ────────────────
log "Обновляю CLIENT_HOST в $SERVER_BOT_ENV..."
if [[ -w "$SERVER_BOT_ENV" ]]; then
    sed -i "s/^CLIENT_HOST=.*/CLIENT_HOST=$TEMP_IP/" "$SERVER_BOT_ENV"
    ok "CLIENT_HOST обновлён"
else
    warn "Нет прав на запись в $SERVER_BOT_ENV — обнови руками: CLIENT_HOST=$TEMP_IP"
fi

if sudo -n systemctl restart "$SERVER_BOT_SERVICE" 2>/dev/null; then
    ok "$SERVER_BOT_SERVICE перезапущен — управление плеером из Telegram работает"
else
    warn "Нет прав на рестарт без пароля — выполни руками: sudo systemctl restart $SERVER_BOT_SERVICE"
    warn "(чтобы это тоже стало автоматическим — см. NOPASSWD-правило в шапке этого скрипта)"
fi

# ── 8. Снимаем временный sudo на кампус-машине ────────────────────────────
log "Снимаю временный NOPASSWD sudo на $CAMPUS..."
sp "echo '$TEMP_PASS' | sudo -S rm -f $SUDOERS_MARKER" >/dev/null 2>&1 \
    && ok "Временный sudo снят" \
    || warn "Не снялся автоматически — сними руками на $CAMPUS: sudo rm $SUDOERS_MARKER"

# Закрываем переиспользуемое SSH-соединение — не обязательно (само истечёт
# через ControlPersist), но чище не оставлять висящий сокет
sshpass -p "$TEMP_PASS" ssh -O exit -o "ControlPath=$SSH_CTL_PATH" "${CAMPUS_USER}@${TEMP_IP}" >/dev/null 2>&1 || true

# ── Итог ────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ВОССТАНОВЛЕНИЕ $CAMPUS ЗАВЕРШЕНО ✅"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Проверка плеера:  ssh $CAMPUS systemctl --user status campus-mpv"
echo "  Тест звука:       ssh $CAMPUS campus-playerctl play ${CAMPUS_HOME}/Media/1/1peremena.mp3"
echo ""
echo "  ⚠️  Когда машина физически переедет на постоянную сеть — обновить:"
echo "      - ~/.ssh/config ($CAMPUS → постоянный IP)"
echo "      - CLIENT_HOST в $SERVER_BOT_ENV → постоянный IP"
echo "      - sudo systemctl restart $SERVER_BOT_SERVICE"
