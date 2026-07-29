#!/bin/bash
# campus-check.sh — диагностика всей системы campus-infra
# Запуск: bash scripts/campus-check.sh
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
hdr()  { echo -e "\n${BOLD}=== $* ===${NC}"; }

SSH="ssh -i /home/kamran/.ssh/campus_bot -o StrictHostKeyChecking=no -o ConnectTimeout=5"

hdr "CAMPUS-WEBUI (Docker)"
if docker inspect campus-webui --format '{{.State.Status}}' 2>/dev/null | grep -q running; then
    ok "campus-webui запущен → http://$(hostname -I | awk '{print $1}'):8090"
else
    fail "campus-webui НЕ запущен!"
    echo "   Запустить: cd /home/kamran/projects/campus-infra && docker compose --profile webui up -d"
fi

hdr "NARIMANOV (nctk — 10.20.0.41)"
if $SSH nctk@10.20.0.41 "echo ok" 2>/dev/null | grep -q ok; then
    ok "SSH доступен"
    STATUS=$($SSH nctk@10.20.0.41 "
        echo -n 'campus-player:'; systemctl is-active campus-player 2>/dev/null || echo inactive
        echo -n 'cron:'; systemctl is-active cron 2>/dev/null || echo inactive
        echo -n 'watchdog:'; systemctl is-active campus-player-watchdog.timer 2>/dev/null || echo inactive
        echo -n 'mpv:'; campus-playerctl status 2>/dev/null | grep STATE | awk '{print \$2}' || echo unknown
    " 2>/dev/null)
    echo "$STATUS" | while IFS=: read k v; do
        v=$(echo "$v" | tr -d ' ')
        [[ "$v" == "active" || "$v" == "stopped" || "$v" == "ok" ]] && ok "$k: $v" || fail "$k: $v"
    done
    LASTLOG=$($SSH nctk@10.20.0.41 "tail -1 /home/nctk/action.log 2>/dev/null" 2>/dev/null)
    ok "Последняя запись: $LASTLOG"
else
    fail "SSH на nctk недоступен!"
fi

hdr "GENCLIK (vm1 — 10.70.0.41)"
if $SSH vm1@10.70.0.41 "echo ok" 2>/dev/null | grep -q ok; then
    ok "SSH доступен"
    STATUS=$($SSH vm1@10.70.0.41 "
        echo -n 'campus-mpv:'; XDG_RUNTIME_DIR=/run/user/\$(id -u) systemctl --user is-active campus-mpv 2>/dev/null || echo inactive
        echo -n 'cron:'; systemctl is-active cron 2>/dev/null || echo inactive
        echo -n 'tg-bot:'; systemctl is-active campus-telegram-bot 2>/dev/null || echo inactive
        echo -n 'mpv-sock:'; [ -S /run/campus-player/mpv.sock ] && echo present || echo missing
    " 2>/dev/null)
    echo "$STATUS" | while IFS=: read k v; do
        v=$(echo "$v" | tr -d ' ')
        [[ "$v" == "active" || "$v" == "present" ]] && ok "$k: $v" || fail "$k: $v"
    done
    LASTLOG=$($SSH vm1@10.70.0.41 "tail -1 /home/vm1/action.log 2>/dev/null" 2>/dev/null)
    ok "Последняя запись: $LASTLOG"
else
    fail "SSH на vm1 недоступен!"
fi

hdr "TELEGRAM БОТЫ (CentOS systemd)"
for svc in tg-campus-narimanov tg-campus-genclik; do
    STATUS=$(systemctl is-active $svc.service 2>/dev/null || echo inactive)
    [[ "$STATUS" == "active" ]] && ok "$svc: active" || warn "$svc: $STATUS"
done

hdr "DOCKER БОТЫ (должны быть ОСТАНОВЛЕНЫ)"
for c in tg-campus-bot tg-campus-genclik; do
    STATE=$(docker inspect $c --format '{{.State.Status}}' 2>/dev/null || echo "not found")
    [[ "$STATE" == "running" ]] && fail "$c ЗАПУЩЕН (конфликт с systemd!)" || ok "$c: $STATE"
done

hdr "ИТОГ"
echo "Для запуска только webui: docker compose --profile webui up -d"
echo "Боты управляются через: systemctl status tg-campus-narimanov tg-campus-genclik"
echo "Музыка на vm1:           ssh vm1@10.70.0.41 campus-playerctl status"
echo "Музыка на nctk:          ssh nctk@10.20.0.41 campus-playerctl status"
