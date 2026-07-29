#!/bin/bash
# Включить перемены на nctk и vm1. Сначала проверка, затем включение.
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
LANDAU_BIN="${LANDAU_BIN:-/home/kamran/landau/bin}"
BIN="${CRON_BIN:-/home/kamran/bin}"
HYMN_SCRIPT="$DIR/campus-cron-hymn-test.sh"

echo "=== 1. Проверка SSH до nctk и vm1 ==="
ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 nctk@10.20.0.41 "echo OK nctk" || { echo "  Ошибка: nctk недоступен"; exit 1; }
ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 vm1@10.70.0.41 "echo OK vm1" || { echo "  Ошибка: vm1 недоступен"; exit 1; }
echo "  OK"

echo ""
echo "=== 2. Скрипты campus-cron-landau и campus-cron-stop ==="
mkdir -p "$BIN"
for f in campus-cron-landau campus-cron-stop; do
  if [[ -f "$LANDAU_BIN/${f}.sh" ]]; then
    cp -f "$LANDAU_BIN/${f}.sh" "$BIN/" && chmod +x "$BIN/${f}.sh" && echo "  $f.sh OK"
  else
    echo "  $f.sh не найден в $LANDAU_BIN"
  fi
done

echo ""
echo "=== 3. Перемены (campus-cron-landau) ==="
HAS_BELLS=$(crontab -l 2>/dev/null | grep -c 'campus-cron-landau' || true)
if [[ "$HAS_BELLS" -eq 0 ]]; then
  if [[ -x "$LANDAU_BIN/install-crontab-landau-both.sh" ]]; then
    CRON_BIN="$BIN" bash "$LANDAU_BIN/install-crontab-landau-both.sh"
  elif [[ -x "$BIN/install-crontab-landau-both.sh" ]]; then
    CRON_BIN="$BIN" bash "$BIN/install-crontab-landau-both.sh"
  else
    echo "  Не найден install-crontab-landau-both.sh"; exit 1
  fi
else
  echo "  Уже включены ($HAS_BELLS записей)"
fi

echo ""
echo "=== 4. himn.mp3 в inbox ==="
LANDAU_ROOT="${LANDAU_ROOT:-/home/kamran/Landau}"
HYMN_SRC=""
[[ -f "$LANDAU_ROOT/1/himn.mp3" ]] && HYMN_SRC="$LANDAU_ROOT/1/himn.mp3"
[[ -z "$HYMN_SRC" ]] && [[ -f "$LANDAU_ROOT/1/HIMN.mp3" ]] && HYMN_SRC="$LANDAU_ROOT/1/HIMN.mp3"
if [[ -n "$HYMN_SRC" ]]; then
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$HYMN_SRC" "nctk@10.20.0.41:/var/lib/campus-player/inbox/himn.mp3" 2>/dev/null && echo "  nctk OK" || echo "  nctk пропуск"
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$HYMN_SRC" "vm1@10.70.0.41:/var/lib/campus-player/inbox/himn.mp3" 2>/dev/null && echo "  vm1 OK" || echo "  vm1 пропуск"
else
  echo "  himn.mp3 не найден — будет in.mp3"
fi

echo ""
echo "=== 5. Тест гимна 07:28 ==="
chmod +x "$HYMN_SCRIPT"
NCTK_ENV="${NCTK_ENV:-/home/kamran/narimanov.env}"
VM1_ENV="${VM1_ENV:-/home/kamran/vm1.env}"
(crontab -l 2>/dev/null | grep -v 'campus-cron-hymn-test' || true
 echo "28 7 * * * NCTK_ENV=$NCTK_ENV VM1_ENV=$VM1_ENV SSH_KEY=$SSH_KEY bash $HYMN_SCRIPT") | crontab -
echo "  Добавлено: 07:28 ежедневно"

echo ""
echo "Готово. crontab -l | grep campus"
