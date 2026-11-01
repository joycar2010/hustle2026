#!/usr/bin/env bash
set -euo pipefail
cd "/home/ec2-user/paper-ab/20261026T110000Z/B"
export PYTHONPATH="/home/ec2-user/paper-ab/20261026T110000Z/B"
export TRADES_DB_PATH="/home/ec2-user/paper-ab/20261026T110000Z/B/ab.db"
export BTC_LIVE_ENABLED=false ETH_TRADING_ENABLED=false WEATHER_LIVE_TRADING_ENABLED=false SPORTS_LIVE_TRADING_ENABLED=false LLM_ENABLED=false
"/home/ec2-user/polymarketbot-auto/.venv/bin/python" "/home/ec2-user/polymarketbot-auto/scripts/write_runtime_manifest.py" "/home/ec2-user/paper-ab/20261026T110000Z/B/runtime-manifest.json" "B"
echo "$BASHPID" > "/home/ec2-user/paper-ab/20261026T110000Z/B/pid"
exec "/home/ec2-user/polymarketbot-auto/.venv/bin/python" -m bot.main --asset BTC
