#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill wallet/API credentials." >&2
  exit 1
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
fi
# Fail closed before the caller can stop Paper or start a live worker.  The
# preflight requires LIVE_EXECUTION_READY, a complete reviewed capability
# manifest, and concrete redeem/reconcile adapters; this release intentionally
# has none, so it must remain unavailable until P1 is completed.
.venv/bin/python -m btc5m preflight
exec .venv/bin/python -m btc5m --live "$@"
