#!/usr/bin/env bash
set -euo pipefail
cd "/home/ec2-user/paper-ab/20261026T110000Z/C"
export PYTHONPATH="/home/ec2-user/paper-ab/20261026T110000Z/C"
export TRADES_DB_PATH="/home/ec2-user/paper-ab/20261026T110000Z/C/ab.db"
export BTC_LIVE_ENABLED=false
export ETH_TRADING_ENABLED=false
export WEATHER_LIVE_TRADING_ENABLED=false
export SPORTS_LIVE_TRADING_ENABLED=false
export LLM_ENABLED=false
export REVERSAL_EXIT_WINDOW_SEC=150
export SECONDS_BEFORE_CLOSE=150
export MIN_T_REMAINING_SEC=90
export REVERSAL_HELD_BID_DRAWDOWN=0.40
echo "$BASHPID" > "/home/ec2-user/paper-ab/20261026T110000Z/C/pid"
exec "/home/ec2-user/polymarketbot-auto/.venv/bin/python" -m bot.main --asset BTC
