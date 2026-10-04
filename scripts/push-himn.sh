#!/bin/bash
# Разослать мастер-копию гимна (с звонком или без) на folder 1 каждого кампуса —
# именно её играет кнопка «ГИМН» на странице и крон по понедельникам в 08:00
# (см. _himn_path_for() в webui/app.py: <Media>/1/himn.mp3).
#
# Запуск:
#   bash scripts/push-himn.sh "/home/kamran/Kamran Music/MEDIASCHOOL/zeng sesi ile HIMN.mp3"
#   bash scripts/push-himn.sh <файл> cgtk bstk     # только по этим кампусам
set -uo pipefail
SRC="${1:?Укажи путь к mp3 первым аргументом}"
shift || true
[[ -f "$SRC" ]] || { echo "Нет файла: $SRC" >&2; exit 1; }
KEY="$HOME/.ssh/campus_bot"
MD5SRC="$(md5sum "$SRC" | cut -d' ' -f1)"

# campus:user:host:home
ALL=(
  "client1:client1:10.20.0.41:/home/client1"
  "client2:client2:10.70.0.41:/home/client2"
  "cgtk:cgtk:10.50.0.41:/home/cgtk"
  "sbtk:sbtk:10.40.0.41:/home/sbtk"
  "wctk:wctk:10.103.0.41:/home/wctk"
  "sptk:sptk:10.40.0.43:/home/sptk"
  "bstk:bstk:10.10.0.41:/home/bstk"
  "bptk:bptk:10.10.0.42:/home/bptk"
)
ONLY=("$@")

for entry in "${ALL[@]}"; do
  IFS=':' read -r campus user host home <<<"$entry"
  if [[ ${#ONLY[@]} -gt 0 ]]; then
    skip=1; for o in "${ONLY[@]}"; do [[ "$o" == "$campus" ]] && skip=0; done
    [[ $skip -eq 1 ]] && continue
  fi
  printf '%-6s ' "$campus"
  if ! ping -c1 -W1 "$host" >/dev/null 2>&1; then echo "офлайн — пропуск"; continue; fi
  if ! scp -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$SRC" "${user}@${host}:${home}/Media/1/himn.mp3" 2>/tmp/push-himn-err; then
    echo "ОШИБКА записи ($(tr -d '\n' </tmp/push-himn-err | tail -c 120))"; continue
  fi
  remote_md5="$(ssh -i "$KEY" -o StrictHostKeyChecking=no "${user}@${host}" "md5sum ${home}/Media/1/himn.mp3 2>/dev/null | cut -d' ' -f1")"
  if [[ "$remote_md5" == "$MD5SRC" ]]; then echo "OK"; else echo "сумма не совпала ($remote_md5)"; fi
done
