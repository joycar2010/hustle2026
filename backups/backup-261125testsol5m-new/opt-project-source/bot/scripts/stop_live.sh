#!/usr/bin/env bash
# Cleanly stop the live bot.
set -e
cd "$(dirname "$0")/.."

stopped=0
for pid_file in bot.pid bot_btc.pid bot_eth.pid; do
  [[ -f "$pid_file" ]] || continue
  pid=$(cat "$pid_file")
  if ps -p "$pid" > /dev/null 2>&1; then
  kill "$pid"
  for _ in 1 2 3 4 5; do
    if ! ps -p "$pid" > /dev/null 2>&1; then break; fi
    sleep 1
  done
  if ps -p "$pid" > /dev/null 2>&1; then
    echo "graceful stop failed; SIGKILL"
    kill -9 "$pid"
  fi
    echo "stopped $pid_file pid=$pid"
    stopped=1
  else
    echo "$pid_file pid $pid not running"
  fi
done
rm -f bot.pid bot_btc.pid bot_eth.pid bot.mode
if [[ "$stopped" == "0" ]]; then
  echo "no live bot process found"
fi
