#!/bin/bash
# Тест локального крона на client2: воспроизведение в 23:20 (1peremena).
# Запуск на сервере: bash campus-infra/scripts/add-test-client2-local-2320.sh
set -e
CLIENT2_HOST="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"
CLIENT2_HOME="/home/$CLIENT2_USER"
HOME="${HOME:-/home/kamran}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIA_SRC="${MEDIA_ROOT:-/home/kamran/Media}"

[ -f "$KEY" ] || { echo "Нет ключа $KEY"; exit 1; }

echo "=== 1. Проверка Media и скриптов на client2 ==="
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "
  mkdir -p ${CLIENT2_HOME}/Media
  [ -f ${CLIENT2_HOME}/Media/2/1peremena.mp3 ] && echo 'Media/2/1peremena.mp3 есть' || echo 'Нет 1peremena — синхронизируем'
"
if ! ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "[ -f ${CLIENT2_HOME}/Media/2/1peremena.mp3 ]" 2>/dev/null; then
  echo "Синхронизация Media на client2..."
  [ -d "$MEDIA_SRC" ] || { echo "Нет $MEDIA_SRC"; exit 1; }
  rsync -az -e "ssh $SSH_OPTS" --delete "$MEDIA_SRC/" "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/Media/" 2>/dev/null || \
    scp $SSH_OPTS -r "$MEDIA_SRC/"* "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/Media/" 2>/dev/null
fi
scp $SSH_OPTS "$SCRIPT_DIR/campus-cron-media-local.sh" "$SCRIPT_DIR/campus-cron-stop-local.sh" "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/" 2>/dev/null || true
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "chmod +x ${CLIENT2_HOME}/campus-cron-media-local.sh ${CLIENT2_HOME}/campus-cron-stop-local.sh 2>/dev/null"

echo ""
echo "=== 2. Добавление теста 23:20 в crontab client2 ==="
TMP=$(mktemp)
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "crontab -l 2>/dev/null" > "$TMP" || true
grep -v '23:20.*campus-cron-media-local.*1peremena\|20 23.*1peremena' "$TMP" > "${TMP}.2" 2>/dev/null && mv "${TMP}.2" "$TMP"
echo "" >> "$TMP"
echo "# Тест локального крона client2 — удалить после проверки" >> "$TMP"
echo "20 23 * * * MEDIA_ROOT=${CLIENT2_HOME}/Media LOG_FILE=${CLIENT2_HOME}/action.log ${CLIENT2_HOME}/campus-cron-media-local.sh 1peremena 130" >> "$TMP"
scp $SSH_OPTS "$TMP" "${CLIENT2_USER}@${CLIENT2_HOST}:/tmp/client2_cron_test" 2>/dev/null
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "crontab /tmp/client2_cron_test && rm -f /tmp/client2_cron_test"
rm -f "$TMP"

echo "Готово. В 23:20 на client2 запустится 1peremena (локальный крон)."
echo "Проверка на client2: tail -5 ${CLIENT2_HOME}/action.log"
echo "После теста: ssh ${CLIENT2_USER}@${CLIENT2_HOST} crontab -e  → удалить строку с 20 23"
