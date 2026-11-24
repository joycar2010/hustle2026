#!/usr/bin/env bash
# BTC 15m C path — separate ledger from BTC 5m
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install -e .
fi
exec .venv/bin/python -m btc5m --series btc15m --mode split_sell "$@"