#!/bin/bash
# Тест локального крона на vm1: воспроизведение в 23:20 (1peremena).
# Запуск на сервере: bash campus-infra/scripts/add-test-vm1-local-2320.sh
set -e
VM1_HOST="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"
VM1_HOME="/home/$VM1_USER"
HOME="${HOME:-/home/kamran}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LANDAU_SRC="${LANDAU_ROOT:-/home/kamran/Landau}"

[ -f "$KEY" ] || { echo "Нет ключа $KEY"; exit 1; }

echo "=== 1. Проверка Landau и скриптов на vm1 ==="
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "
  mkdir -p ${VM1_HOME}/Landau
  [ -f ${VM1_HOME}/Landau/2/1peremena.mp3 ] && echo 'Landau/2/1peremena.mp3 есть' || echo 'Нет 1peremena — синхронизируем'
"
if ! ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "[ -f ${VM1_HOME}/Landau/2/1peremena.mp3 ]" 2>/dev/null; then
  echo "Синхронизация Landau на vm1..."
  [ -d "$LANDAU_SRC" ] || { echo "Нет $LANDAU_SRC"; exit 1; }
  rsync -az -e "ssh $SSH_OPTS" --delete "$LANDAU_SRC/" "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/Landau/" 2>/dev/null || \
    scp $SSH_OPTS -r "$LANDAU_SRC/"* "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/Landau/" 2>/dev/null
fi
scp $SSH_OPTS "$SCRIPT_DIR/campus-cron-landau-local.sh" "$SCRIPT_DIR/campus-cron-stop-local.sh" "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/" 2>/dev/null || true
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "chmod +x ${VM1_HOME}/campus-cron-landau-local.sh ${VM1_HOME}/campus-cron-stop-local.sh 2>/dev/null"

echo ""
echo "=== 2. Добавление теста 23:20 в crontab vm1 ==="
TMP=$(mktemp)
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "crontab -l 2>/dev/null" > "$TMP" || true
grep -v '23:20.*campus-cron-landau-local.*1peremena\|20 23.*1peremena' "$TMP" > "${TMP}.2" 2>/dev/null && mv "${TMP}.2" "$TMP"
echo "" >> "$TMP"
echo "# Тест локального крона vm1 — удалить после проверки" >> "$TMP"
echo "20 23 * * * LANDAU_ROOT=${VM1_HOME}/Landau LOG_FILE=${VM1_HOME}/action.log ${VM1_HOME}/campus-cron-landau-local.sh 1peremena 130" >> "$TMP"
scp $SSH_OPTS "$TMP" "${VM1_USER}@${VM1_HOST}:/tmp/vm1_cron_test" 2>/dev/null
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "crontab /tmp/vm1_cron_test && rm -f /tmp/vm1_cron_test"
rm -f "$TMP"

echo "Готово. В 23:20 на vm1 запустится 1peremena (локальный крон)."
echo "Проверка на vm1: tail -5 ${VM1_HOME}/action.log"
echo "После теста: ssh ${VM1_USER}@${VM1_HOST} crontab -e  → удалить строку с 20 23"
