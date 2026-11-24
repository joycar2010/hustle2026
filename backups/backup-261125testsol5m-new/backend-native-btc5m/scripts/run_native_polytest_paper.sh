#!/usr/bin/env bash
set -euo pipefail
R=/home/ec2-user/polymarketbot-test/releases/polytest-native-btc5m-20261118T181500Z
LEGACY_RELEASE=/home/ec2-user/polymarketbot-test/releases/polytest-polyauto-a-20261118T000000Z
echo $$ > "$LEGACY_RELEASE/bot_btc.pid"
echo paper > "$LEGACY_RELEASE/bot.mode"
trap 'rm -f "$LEGACY_RELEASE/bot_btc.pid"' EXIT
exec "$R/.venv/bin/python" -m btc5m
