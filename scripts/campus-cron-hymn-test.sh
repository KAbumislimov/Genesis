#!/bin/bash
# Тест гимна 07:28 — 10 сек на nctk и vm1
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

NCTK_ENV="${NCTK_ENV:-/home/kamran/narimanov.env}"
[[ -r "$NCTK_ENV" ]] && . "$NCTK_ENV" 2>/dev/null
run_host "${CLIENT_USER:-nctk}" "${CLIENT_HOST:-10.20.0.41}"

VM1_ENV="${VM1_ENV:-/home/kamran/vm1.env}"
[[ -r "$VM1_ENV" ]] && . "$VM1_ENV" 2>/dev/null
run_host "${CLIENT_USER:-vm1}" "${CLIENT_HOST:-10.70.0.41}"
