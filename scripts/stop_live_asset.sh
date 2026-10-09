#!/usr/bin/env bash
# Stop one live worker without touching unrelated asset workers.
set -euo pipefail
cd "$(dirname "$0")/.."
asset="${1:?asset required}"
case "$asset" in
  BTC) pid_file=bot_btc.pid ;;
  ETH) pid_file=bot_eth.pid ;;
  ALL) pid_file="" ;;
  *) echo "unsupported asset: $asset" >&2; exit 2 ;;
esac
stopped=0
if [[ "$asset" == "ALL" ]]; then
  "$0" BTC || true
  "$0" ETH || true
  exit 0
fi
if [[ -f "$pid_file" ]]; then
  pid=$(cat "$pid_file")
  if ps -p "$pid" >/dev/null 2>&1; then
    kill "$pid"
    for _ in 1 2 3 4 5; do
      ps -p "$pid" >/dev/null 2>&1 || break
      sleep 1
    done
    if ps -p "$pid" >/dev/null 2>&1; then kill -9 "$pid"; fi
    echo "stopped $pid_file pid=$pid"
    stopped=1
  fi
  rm -f "$pid_file"
fi
if [[ "$asset" == "BTC" && -f bot.pid ]]; then rm -f bot.pid; fi
if [[ "$stopped" == "0" ]]; then echo "no $asset live worker found"; fi
if [[ ! -f bot_btc.pid && ! -f bot_eth.pid ]]; then rm -f bot.mode; fi
