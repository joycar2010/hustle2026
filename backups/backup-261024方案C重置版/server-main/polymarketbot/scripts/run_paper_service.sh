#!/usr/bin/env bash
set -euo pipefail
cd /home/ec2-user/polymarketbot
umask 077
printf '%s\n' "$$" > bot.pid
printf '%s\n' "$$" > bot_btc.pid
printf 'paper\n' > bot.mode
exec .venv/bin/python -u -m bot.main --asset BTC
