#!/usr/bin/env bash
set -euo pipefail
release=/home/ec2-user/polymarketbot-test/releases/polytest-polyauto-a-20261118T000000Z
printf '%s\n' "$$" > "$release/bot_btc.pid"
printf '%s\n' paper > "$release/bot.mode"
trap 'rm -f "$release/bot_btc.pid"' EXIT
exec "$release/.venv/bin/python" -m bot.main --asset BTC
