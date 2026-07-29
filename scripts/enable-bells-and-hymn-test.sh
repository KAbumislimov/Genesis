#!/bin/bash
# Включить перемены на client1 и client2. Сначала проверка, затем включение.
# Тест гимна: 07:28 (10 сек).
# Запуск: bash scripts/enable-bells-and-hymn-test.sh

set -e
SSH_KEY="${SSH_KEY:-}"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/id_ed25519" ]] && SSH_KEY="$HOME/.ssh/id_ed25519"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/campus_bot" ]] && SSH_KEY="$HOME/.ssh/campus_bot"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/id_rsa" ]] && SSH_KEY="$HOME/.ssh/id_rsa"
[[ -z "$SSH_KEY" ]] && { echo "Нет SSH ключа"; exit 1; }
export SSH_KEY

DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIA_BIN="${MEDIA_BIN:-/home/kamran/media/bin}"
BIN="${CRON_BIN:-/home/kamran/bin}"
HYMN_SCRIPT="$DIR/campus-cron-hymn-test.sh"

echo "=== 1. Проверка SSH до client1 и client2 ==="
ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 client1@10.20.0.41 "echo OK client1" || { echo "  Ошибка: client1 недоступен"; exit 1; }
ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 client2@10.70.0.41 "echo OK client2" || { echo "  Ошибка: client2 недоступен"; exit 1; }
echo "  OK"

echo ""
echo "=== 2. Скрипты campus-cron-media и campus-cron-stop ==="
mkdir -p "$BIN"
for f in campus-cron-media campus-cron-stop; do
  if [[ -f "$MEDIA_BIN/${f}.sh" ]]; then
    cp -f "$MEDIA_BIN/${f}.sh" "$BIN/" && chmod +x "$BIN/${f}.sh" && echo "  $f.sh OK"
  else
    echo "  $f.sh не найден в $MEDIA_BIN"
  fi
done

echo ""
echo "=== 3. Перемены (campus-cron-media) ==="
HAS_BELLS=$(crontab -l 2>/dev/null | grep -c 'campus-cron-media' || true)
if [[ "$HAS_BELLS" -eq 0 ]]; then
  if [[ -x "$MEDIA_BIN/install-crontab-media-both.sh" ]]; then
    CRON_BIN="$BIN" bash "$MEDIA_BIN/install-crontab-media-both.sh"
  elif [[ -x "$BIN/install-crontab-media-both.sh" ]]; then
    CRON_BIN="$BIN" bash "$BIN/install-crontab-media-both.sh"
  else
    echo "  Не найден install-crontab-media-both.sh"; exit 1
  fi
else
  echo "  Уже включены ($HAS_BELLS записей)"
fi

echo ""
echo "=== 4. himn.mp3 в inbox ==="
MEDIA_ROOT="${MEDIA_ROOT:-/home/kamran/Media}"
HYMN_SRC=""
[[ -f "$MEDIA_ROOT/1/himn.mp3" ]] && HYMN_SRC="$MEDIA_ROOT/1/himn.mp3"
[[ -z "$HYMN_SRC" ]] && [[ -f "$MEDIA_ROOT/1/HIMN.mp3" ]] && HYMN_SRC="$MEDIA_ROOT/1/HIMN.mp3"
if [[ -n "$HYMN_SRC" ]]; then
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$HYMN_SRC" "client1@10.20.0.41:/var/lib/campus-player/inbox/himn.mp3" 2>/dev/null && echo "  client1 OK" || echo "  client1 пропуск"
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$HYMN_SRC" "client2@10.70.0.41:/var/lib/campus-player/inbox/himn.mp3" 2>/dev/null && echo "  client2 OK" || echo "  client2 пропуск"
else
  echo "  himn.mp3 не найден — будет in.mp3"
fi

echo ""
echo "=== 5. Тест гимна 07:28 ==="
chmod +x "$HYMN_SCRIPT"
CLIENT1_ENV="${CLIENT1_ENV:-/home/kamran/client1.env}"
CLIENT2_ENV="${CLIENT2_ENV:-/home/kamran/client2.env}"
(crontab -l 2>/dev/null | grep -v 'campus-cron-hymn-test' || true
 echo "28 7 * * * CLIENT1_ENV=$CLIENT1_ENV CLIENT2_ENV=$CLIENT2_ENV SSH_KEY=$SSH_KEY bash $HYMN_SCRIPT") | crontab -
echo "  Добавлено: 07:28 ежедневно"

echo ""
echo "Готово. crontab -l | grep campus"
