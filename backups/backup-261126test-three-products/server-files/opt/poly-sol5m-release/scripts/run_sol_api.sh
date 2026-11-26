#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install -e .
fi
export PRODUCT_KEY=sol5m SERIES_SLUG=sol-up-or-down-5m
export MARKET_SLUG_PREFIX=sol-updown-5m CRYPTO_ASSET=sol WINDOW_SEC=300
export LIVE=false LIVE_TRADING_ENABLED=false
exec .venv/bin/python -m sol5m api --port "${DASHBOARD_PORT:-8095}"

