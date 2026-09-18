#!/usr/bin/env bash
# Launch LIVE mode bots (REAL ORDERS, REAL MONEY).
# For paper trading, use scripts/run_paper.sh instead.
set -e
cd "$(dirname "$0")/.."

if [[ -f bot_btc.pid ]] && ps -p "$(cat bot_btc.pid)" > /dev/null 2>&1; then
  echo "BTC bot already running pid=$(cat bot_btc.pid)"
  echo "stop it first: scripts/stop_live.sh"
  exit 1
fi
if [[ -f bot_eth.pid ]] && ps -p "$(cat bot_eth.pid)" > /dev/null 2>&1; then
  echo "ETH bot already running pid=$(cat bot_eth.pid)"
  echo "stop it first: scripts/stop_live.sh"
  exit 1
fi

mkdir -p logs
ts=$(date +%Y%m%d_%H%M%S)
btc_log="logs/bot_btc_${ts}.log"
eth_log="logs/bot_eth_${ts}.log"

ln -sfn "bot_btc_${ts}.log" logs/bot_btc_current.log
nohup .venv/bin/python -m bot.main --live --asset BTC > "$btc_log" 2>&1 &
btc_pid=$!
echo "$btc_pid" > bot.pid
echo "$btc_pid" > bot_btc.pid
echo "live" > bot.mode
disown 2>/dev/null || true
sleep 1

if ps -p "$btc_pid" > /dev/null 2>&1; then
  echo "BTC LIVE bot started pid=$btc_pid"
  echo "  log: $btc_log"
else
  echo "FAILED to start BTC bot - see $btc_log"
  exit 1
fi

if grep -Eiq '^ETH_TRADING_ENABLED=true' .env; then
  ln -sfn "bot_eth_${ts}.log" logs/bot_eth_current.log
  nohup .venv/bin/python -m bot.main --live --asset ETH > "$eth_log" 2>&1 &
  eth_pid=$!
  echo "$eth_pid" > bot_eth.pid
  disown 2>/dev/null || true
  sleep 1
  if ps -p "$eth_pid" > /dev/null 2>&1; then
    echo "ETH LIVE bot started pid=$eth_pid"
    echo "  log: $eth_log"
  else
    echo "FAILED to start ETH bot - see $eth_log"
    exit 1
  fi
else
  rm -f bot_eth.pid
  echo "ETH live disabled; set ETH_TRADING_ENABLED=true to trade ETH"
fi

echo "REAL ORDERS will be placed against your funded deposit wallet"
echo "stop: scripts/stop_live.sh"
