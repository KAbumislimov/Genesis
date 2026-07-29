#!/bin/bash
# Установка на vm1 локального крона как на nctk: свои скрипты и Landau, пн-пт.
# Запуск на сервере: bash campus-infra/scripts/install-crontab-landau-local-vm1.sh
# Требует: rsync/scp, SSH на vm1 по ключу campus_bot.
set -e
VM1_HOST="${VM1_HOST:-10.70.0.41}"
VM1_USER="${VM1_USER:-vm1}"
VM1_HOME="/home/$VM1_USER"
HOME="${HOME:-/home/kamran}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
LANDAU_SRC="${LANDAU_ROOT:-/home/kamran/Landau}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VOL=130

[ -d "$LANDAU_SRC" ] || { echo "Нет $LANDAU_SRC"; exit 1; }
[ -f "$KEY" ] || { echo "Нет ключа $KEY"; exit 1; }

echo "=== 1. Синхронизация Landau на vm1 ==="
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "mkdir -p ${VM1_HOME}/Landau"
rsync -az -e "ssh $SSH_OPTS" --delete \
  "$LANDAU_SRC/" "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/Landau/" 2>/dev/null || \
  scp $SSH_OPTS -r "$LANDAU_SRC/"* "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/Landau/" 2>/dev/null

echo "=== 2. Копирование скриптов на vm1 ==="
scp $SSH_OPTS \
  "$SCRIPT_DIR/campus-cron-landau-local.sh" \
  "$SCRIPT_DIR/campus-cron-stop-local.sh" \
  "${VM1_USER}@${VM1_HOST}:${VM1_HOME}/"
ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "chmod +x ${VM1_HOME}/campus-cron-landau-local.sh ${VM1_HOME}/campus-cron-stop-local.sh"

echo "=== 3. Установка crontab на vm1 (пн-пт, как nctk) ==="
# Расписание как в install-crontab-landau-both, но локальные скрипты + VOL 130
CRON=$(cat << 'CRON'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
MAILTO=""
HOME=VM1_HOME_PLACEHOLDER

45 7 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh utro 130
59 7 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
0 8 * * 1 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh himn 160
3 8 * * 1 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
40 8 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 1peremena 130
45 8 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
25 9 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 2peremena 130
35 9 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
15 10 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 3peremena 130
20 10 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
0 11 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 4peremena 130
5 11 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
45 11 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 5peremena 130
55 11 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
35 12 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 6peremena 130
40 12 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
20 13 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 7peremena 130
30 13 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
10 14 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 8peremena 130
20 14 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
55 14 * * 1-5 LANDAU_ROOT=VM1_HOME_PLACEHOLDER/Landau LOG_FILE=VM1_HOME_PLACEHOLDER/action.log VM1_HOME_PLACEHOLDER/campus-cron-landau-local.sh 9peremena 130
10 15 * * 1-5 VM1_HOME_PLACEHOLDER/campus-cron-stop-local.sh
CRON
)
CRON="${CRON//VM1_HOME_PLACEHOLDER/$VM1_HOME}"
echo "$CRON" | ssh $SSH_OPTS "${VM1_USER}@${VM1_HOST}" "crontab -"

echo "Готово. На vm1 установлен локальный крон (как на nctk), пн-пт, VOL=130."
echo "Проверка: ssh ${VM1_USER}@${VM1_HOST} 'crontab -l | head -20'"
echo ""
echo "Если vm1 теперь играет сам — уберите записи vm1.env с сервера:"
echo "  crontab -e  → удалить строки с ENV_FILE=/home/kamran/vm1.env"
