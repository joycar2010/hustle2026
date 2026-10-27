#!/usr/bin/env bash
set -euo pipefail

# Production Paper BTC launcher for the C shadow candidate.
# Keep the C source isolated while writing to the production Paper ledger
# consumed by the dashboard. Live trading remains explicitly disabled by the
# C .env and is also forced off here.
asset="${1:?asset required}"
if [[ "$asset" != "BTC" ]]; then
  echo "C production Paper launcher only supports BTC" >&2
  exit 2
fi

source_dir="/home/ec2-user/paper-ab/20261022T020933Z/C"
prod_root="/home/ec2-user/polymarketbot-auto"
cd "$source_dir"
export PYTHONPATH="$source_dir"
export TRADES_DB_PATH="$prod_root/trades-auto.db"
export BTC_LIVE_ENABLED=false
export ETH_TRADING_ENABLED=false
export WEATHER_LIVE_TRADING_ENABLED=false
export SPORTS_LIVE_TRADING_ENABLED=false

# The dashboard reads this marker for the production Paper worker state.
printf 'paper\n' > "$prod_root/bot.mode"
printf '%s\n' "$$" > "$prod_root/bot_btc.pid"
exec "$prod_root/.venv/bin/python" -m bot.main --asset "$asset"
