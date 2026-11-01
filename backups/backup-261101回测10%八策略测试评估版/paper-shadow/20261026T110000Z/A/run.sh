#!/usr/bin/env bash
set -euo pipefail
cd "/home/ec2-user/paper-ab/20261026T110000Z/A"
export PYTHONPATH="/home/ec2-user/paper-ab/20261026T110000Z/A"
export TRADES_DB_PATH="/home/ec2-user/paper-ab/20261026T110000Z/A/ab.db"
export BTC_LIVE_ENABLED=false ETH_TRADING_ENABLED=false WEATHER_LIVE_TRADING_ENABLED=false SPORTS_LIVE_TRADING_ENABLED=false LLM_ENABLED=false
"/home/ec2-user/polymarketbot-auto/.venv/bin/python" "/home/ec2-user/polymarketbot-auto/scripts/write_runtime_manifest.py" "/home/ec2-user/paper-ab/20261026T110000Z/A/runtime-manifest.json" "A"
echo "$BASHPID" > "/home/ec2-user/paper-ab/20261026T110000Z/A/pid"
exec "/home/ec2-user/polymarketbot-auto/.venv/bin/python" -m bot.main --asset BTC
