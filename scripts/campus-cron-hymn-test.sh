#!/bin/bash
# Тест гимна 07:28 — 10 сек на client1 и client2
set -e
INBOX="/var/lib/campus-player/inbox"
VOL="${CRON_VOL:-70}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
[[ -f "$HOME/.ssh/campus_bot" ]] && SSH_KEY="$HOME/.ssh/campus_bot"
[[ -f "$HOME/.ssh/id_rsa" ]] && [[ ! -f "$SSH_KEY" ]] && SSH_KEY="$HOME/.ssh/id_rsa"

run_host() {
  local u="$1" h="$2"
  ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$u@$h" "
    F='$INBOX/himn.mp3'; test -f \"\$F\" || F='$INBOX/in.mp3'
    /usr/local/bin/campus-playerctl stop 2>/dev/null || true
    /usr/local/bin/campus-playerctl vol $VOL 2>/dev/null || true
    /usr/local/bin/campus-playerctl play \"\$F\" $VOL 2>/dev/null &
    sleep 10
    /usr/local/bin/campus-playerctl stop 2>/dev/null || true
  " 2>/dev/null || true
}

CLIENT1_ENV="${CLIENT1_ENV:-/home/kamran/client1.env}"
[[ -r "$CLIENT1_ENV" ]] && . "$CLIENT1_ENV" 2>/dev/null
run_host "${CLIENT_USER:-client1}" "${CLIENT_HOST:-10.20.0.41}"

CLIENT2_ENV="${CLIENT2_ENV:-/home/kamran/client2.env}"
[[ -r "$CLIENT2_ENV" ]] && . "$CLIENT2_ENV" 2>/dev/null
run_host "${CLIENT_USER:-client2}" "${CLIENT_HOST:-10.70.0.41}"
