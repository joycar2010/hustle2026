#!/usr/bin/env bash
set -euo pipefail
release=/home/ec2-user/polymarketbot-test/releases/polytest-polyauto-a-20261118T000000Z
export PYTHONPATH="$release"
echo $$ > "$release/bot_btc.pid"
echo paper > "$release/bot.mode"
exec "$release/.venv/bin/python" -m bot.main --asset BTC
