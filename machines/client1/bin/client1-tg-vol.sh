#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"

case "$ACTION" in
  up)   amixer -c 1 sset Speaker 10%+ ;;
  down) amixer -c 1 sset Speaker 10%- ;;
  set)  amixer -c 1 sset Speaker "${2:-70}%" ;;
  *) echo "ERR"; exit 1 ;;
esac

echo "OK"
