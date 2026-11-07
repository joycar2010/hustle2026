#!/usr/bin/env bash
set -euo pipefail
asset="${1:?asset required}"
[[ "$asset" == BTC ]] || exit 2
source_dir="/home/ec2-user/polymarketbot-test/releases/polyauto-d-20261101"
cd "$source_dir"
export PYTHONPATH="$source_dir"
export TRADES_DB_PATH="/home/ec2-user/polymarketbot-test/releases/85056d2-20261025/trades-test.db"
export BTC_LIVE_ENABLED=false
export ETH_TRADING_ENABLED=false
export WEATHER_LIVE_TRADING_ENABLED=false
export SPORTS_LIVE_TRADING_ENABLED=false
python="$source_dir/.venv/bin/python"
"$python" "$source_dir/scripts/write_runtime_manifest.py" "$source_dir/runtime-manifest.json" D-production
printf 'paper\n' > "$source_dir/bot.mode"
printf '%s\n' "$$" > "$source_dir/bot_btc.pid"
exec "$python" -m bot.main --asset "$asset"
