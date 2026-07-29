#!/bin/bash
# Установка на client2 локального крона как на client1: свои скрипты и Media, пн-пт.
# Запуск на сервере: bash campus-infra/scripts/install-crontab-media-local-client2.sh
# Требует: rsync/scp, SSH на client2 по ключу campus_bot.
set -e
CLIENT2_HOST="${CLIENT2_HOST:-10.70.0.41}"
CLIENT2_USER="${CLIENT2_USER:-client2}"
CLIENT2_HOME="/home/$CLIENT2_USER"
HOME="${HOME:-/home/kamran}"
KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
MEDIA_SRC="${MEDIA_ROOT:-/home/kamran/Media}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VOL=130

[ -d "$MEDIA_SRC" ] || { echo "Нет $MEDIA_SRC"; exit 1; }
[ -f "$KEY" ] || { echo "Нет ключа $KEY"; exit 1; }

echo "=== 1. Синхронизация Media на client2 ==="
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "mkdir -p ${CLIENT2_HOME}/Media"
rsync -az -e "ssh $SSH_OPTS" --delete \
  "$MEDIA_SRC/" "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/Media/" 2>/dev/null || \
  scp $SSH_OPTS -r "$MEDIA_SRC/"* "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/Media/" 2>/dev/null

echo "=== 2. Копирование скриптов на client2 ==="
scp $SSH_OPTS \
  "$SCRIPT_DIR/campus-cron-media-local.sh" \
  "$SCRIPT_DIR/campus-cron-stop-local.sh" \
  "${CLIENT2_USER}@${CLIENT2_HOST}:${CLIENT2_HOME}/"
ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "chmod +x ${CLIENT2_HOME}/campus-cron-media-local.sh ${CLIENT2_HOME}/campus-cron-stop-local.sh"

echo "=== 3. Установка crontab на client2 (пн-пт, как client1) ==="
# Расписание как в install-crontab-media-both, но локальные скрипты + VOL 130
CRON=$(cat << 'CRON'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
MAILTO=""
HOME=CLIENT2_HOME_PLACEHOLDER

45 7 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh utro 130
59 7 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
0 8 * * 1 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh himn 160
3 8 * * 1 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
40 8 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 1peremena 130
45 8 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
25 9 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 2peremena 130
35 9 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
15 10 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 3peremena 130
20 10 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
0 11 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 4peremena 130
5 11 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
45 11 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 5peremena 130
55 11 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
35 12 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 6peremena 130
40 12 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
20 13 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 7peremena 130
30 13 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
10 14 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 8peremena 130
20 14 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
55 14 * * 1-5 MEDIA_ROOT=CLIENT2_HOME_PLACEHOLDER/Media LOG_FILE=CLIENT2_HOME_PLACEHOLDER/action.log CLIENT2_HOME_PLACEHOLDER/campus-cron-media-local.sh 9peremena 130
10 15 * * 1-5 CLIENT2_HOME_PLACEHOLDER/campus-cron-stop-local.sh
CRON
)
CRON="${CRON//CLIENT2_HOME_PLACEHOLDER/$CLIENT2_HOME}"
echo "$CRON" | ssh $SSH_OPTS "${CLIENT2_USER}@${CLIENT2_HOST}" "crontab -"

echo "Готово. На client2 установлен локальный крон (как на client1), пн-пт, VOL=130."
echo "Проверка: ssh ${CLIENT2_USER}@${CLIENT2_HOST} 'crontab -l | head -20'"
echo ""
echo "Если client2 теперь играет сам — уберите записи client2.env с сервера:"
echo "  crontab -e  → удалить строки с ENV_FILE=/home/kamran/client2.env"
