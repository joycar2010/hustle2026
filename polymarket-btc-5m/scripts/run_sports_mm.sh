#!/usr/bin/env bash
# ATP / CS sports_mm paper (external odds bus + PRE_GAME state machine)
# Usage: ./scripts/run_sports_mm.sh atp
#        ./scripts/run_sports_mm.sh cs
set -euo pipefail
cd "$(dirname "$0")/.."
SERIES="${1:-atp}"
shift || true
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install -e .
fi
exec .venv/bin/python -m btc5m --series "$SERIES" --mode sports_mm "$@"
