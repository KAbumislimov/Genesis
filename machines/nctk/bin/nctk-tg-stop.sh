#!/usr/bin/env bash
set -euo pipefail

PIDFILE="/run/user/1000/nctk-tg-mpv.pid"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  kill "$(cat "$PIDFILE")" || true
  sleep 0.2
fi

rm -f "$PIDFILE" 2>/dev/null || true
echo "OK"
