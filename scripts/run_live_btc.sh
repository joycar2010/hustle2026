#!/usr/bin/env bash
# Isolated polyauto BTC live launcher.  This script deliberately never starts
# ETH or any weather/sports worker.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -Eiq '^POLYAUTO_INSTANCE="?(true|1|yes|on|auto)"?[[:space:]]*$' .env; then
  echo "run_live_btc.sh is restricted to a POLYAUTO_INSTANCE deployment" >&2
  exit 2
fi
if ! grep -Eiq '^BTC_LIVE_ENABLED="?(true|1|yes|on)"?[[:space:]]*$' .env; then
  echo "BTC_LIVE_ENABLED=false; enable the isolated BTC live switch first" >&2
  exit 2
fi

.venv/bin/python scripts/live_preflight.py
.venv/bin/python scripts/verify_setup.py
for pid_file in bot.pid bot_btc.pid bot_eth.pid; do
  if [[ -f "$pid_file" ]] && ps -p "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "bot already running pid=$(cat "$pid_file") ($pid_file); stop it first" >&2
    exit 1
  fi
done

mkdir -p logs
ts=$(date +%Y%m%d_%H%M%S)
log_file="logs/bot_btc_${ts}.log"
ln -sfn "bot_btc_${ts}.log" logs/bot_btc_current.log
nohup .venv/bin/python -m bot.main --live --asset BTC >"$log_file" 2>&1 &
pid=$!
echo "$pid" > bot.pid
echo "$pid" > bot_btc.pid
echo live > bot.mode
disown 2>/dev/null || true
sleep 1
if ! ps -p "$pid" >/dev/null 2>&1; then
  echo "FAILED to start BTC bot; see $log_file" >&2
  exit 1
fi
echo "BTC LIVE bot started pid=$pid"
echo "log: $log_file"
