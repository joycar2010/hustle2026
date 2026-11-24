#!/usr/bin/env bash
set -euo pipefail
asset="${1:?asset required}"
cd "$(dirname "$0")/.."
case "$asset" in BTC) pidfile=bot_btc.pid;; ETH) pidfile=bot_eth.pid;; *) echo "unsupported asset" >&2; exit 2;; esac
echo "$$" > "$pidfile"
echo paper > bot.mode
exec .venv/bin/python -m bot.main --asset "$asset"
