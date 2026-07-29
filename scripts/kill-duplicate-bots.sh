#!/bin/bash
# Убивает дубликаты ботов — оставляет по 1 процессу на каждый скрипт
# Cron: каждую минуту. Запускать на campus-server (10.10.4.120)

for script in /opt/tg-campus-bot/bot_narimanov.py /opt/tg-campus-bot/bot_genclik.py; do
  [[ ! -f "$script" ]] && continue
  pids=($(pgrep -f "$script" 2>/dev/null || true))
  if [[ ${#pids[@]} -gt 1 ]]; then
    keep=${pids[0]}
    for pid in "${pids[@]}"; do
      [[ "$pid" != "$keep" ]] && kill "$pid" 2>/dev/null || true
    done
  fi
done
