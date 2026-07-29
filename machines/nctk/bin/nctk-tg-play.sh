#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-}"
VOL="${VOL:-70}"

PIDFILE="/run/user/1000/nctk-tg-mpv.pid"
LOG="/tmp/nctk-tg-player.log"

[[ -n "$FILE" ]] || exit 1

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  kill "$(cat "$PIDFILE")" || true
  sleep 0.2
fi
rm -f "$PIDFILE" 2>/dev/null || true

amixer -c 1 sset Speaker "${VOL}%" unmute >/dev/null 2>&1 || true

nohup mpv \
  --no-video \
  --audio-device=alsa/hw:1,0 \
  --really-quiet \
  "$FILE" >>"$LOG" 2>&1 &

echo $! > "$PIDFILE"
echo "OK"
