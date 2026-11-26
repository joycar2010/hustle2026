#!/usr/bin/env bash
# Cleanly stop the live bot.
set -e
cd "$(dirname "$0")/.."

managed_unit=$(.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
print(os.environ.get('LIVE_WORKER_SYSTEMD_UNIT') or dotenv_values('.env').get('LIVE_WORKER_SYSTEMD_UNIT') or '')
PY
)
if [[ -n "$managed_unit" ]]; then
  if [[ "$managed_unit" != "polymarket-test-btc-live.service" ]]; then
    echo "unsupported managed BTC worker unit" >&2
    exit 2
  fi
  unit_root=$(systemctl show "$managed_unit" -p WorkingDirectory --value)
  if [[ -z "$unit_root" || "$(readlink -f "$unit_root")" != "$(pwd -P)" ]]; then
    echo "managed BTC service does not point to this release" >&2
    exit 2
  fi
  sudo -n systemctl stop "$managed_unit"
  echo "BTC LIVE supervised worker stopped unit=$managed_unit"
  exit 0
fi

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
