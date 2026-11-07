#!/usr/bin/env bash
# Launch the isolated polyauto BTC/ETH live workers after a shared preflight.
# Weather and sports are intentionally never started here.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -Eiq '^POLYAUTO_INSTANCE="?(true|1|yes|on|auto)"?[[:space:]]*$' .env; then
  echo "run_live_polyauto.sh is restricted to a POLYAUTO_INSTANCE deployment" >&2
  exit 2
fi
.venv/bin/python scripts/live_preflight.py
.venv/bin/python scripts/verify_setup.py

for pid_file in bot.pid bot_btc.pid bot_eth.pid; do
  if [[ -f "$pid_file" ]] && ps -p "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "bot already running pid=$(cat "$pid_file") ($pid_file); stop paper/live workers first" >&2
    exit 1
  fi
done

mkdir -p logs
ts=$(date +%Y%m%d_%H%M%S)

start_asset() {
  local asset="$1"
  local flag="$2"
  local log_file="logs/bot_${asset,,}_${ts}.log"
  if ! grep -Eiq "^${flag}=\"?(true|1|yes|on)\"?[[:space:]]*$" .env; then
    echo "${asset} live disabled; skipping"
    return 0
  fi
  ln -sfn "bot_${asset,,}_${ts}.log" "logs/bot_${asset,,}_current.log"
  nohup .venv/bin/python -m bot.main --live --asset "$asset" >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "bot_${asset,,}.pid"
  [[ "$asset" == "BTC" ]] && echo "$pid" > bot.pid
  sleep 1
  if ! ps -p "$pid" >/dev/null 2>&1; then
    echo "FAILED to start ${asset} live; see ${log_file}" >&2
    return 1
  fi
  echo "${asset} LIVE bot started pid=${pid}"
  echo "log: ${log_file}"
}

start_asset BTC BTC_LIVE_ENABLED
start_asset ETH ETH_TRADING_ENABLED
echo live > bot.mode
echo "BTC/ETH REAL ORDERS are enabled; weather and sports remain paper-only"
