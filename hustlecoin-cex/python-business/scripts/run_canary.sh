#!/usr/bin/env bash
#
# One-click wrapper for the IOC-OTOCO borrow canary:
#   (only when --arm) stop cex-arb-engine -> run canary -> ALWAYS restart engine
#
# The engine is paused ONLY when actually firing orders (--arm), so the UID-weight
# counter is clean for the measurement. A DRY RUN never touches the engine.
# The engine is restarted via an EXIT trap, so it comes back even if the canary
# errors out or you Ctrl-C mid-run.
#
# NOTE: stopping cex-arb-engine pauses trading for ALL sub-accounts for ~1-2 min.
#
# USAGE (on the server, 57.183.43.62):
#   export BINANCE_API_KEY=...      # a cross-margin-enabled sub-account key
#   export BINANCE_API_SECRET=...
#   ./run_canary.sh                         # dry run (engine untouched)
#   ./run_canary.sh --arm                   # stop engine, fire A+B+C, restart engine
#   ./run_canary.sh --arm --symbol FILUSDT --notional 15 --tests A,B
#
set -euo pipefail

SERVICE="cex-arb-engine"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CANARY="$SCRIPT_DIR/canary_otoco_borrow.py"

# make `import app.db...` resolve when loading keys from the DB via --account
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$CANARY" ]]; then
  echo "ERROR: canary script not found at $CANARY" >&2
  exit 2
fi

# --- flags: are we arming, and are we sourcing keys from the DB? ---
ARMED="no"; USES_DB="no"
for a in "$@"; do
  [[ "$a" == "--arm" ]] && ARMED="yes"
  [[ "$a" == "--account" ]] && USES_DB="yes"
done

# --- preflight: need creds (env) UNLESS --account pulls them from the DB ---
if [[ "$USES_DB" == "no" && ( -z "${BINANCE_API_KEY:-}" || -z "${BINANCE_API_SECRET:-}" ) ]]; then
  echo "ERROR: pass --account <note|email> (DB keys), or export BINANCE_API_KEY/SECRET." >&2
  exit 2
fi

if [[ "$ARMED" == "yes" ]]; then
  WAS_ACTIVE="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
  restore_engine() {
    if [[ "${WAS_ACTIVE:-}" == "active" ]]; then
      echo ">>> restarting $SERVICE"
      sudo systemctl start "$SERVICE" || echo "WARNING: failed to restart $SERVICE — start it manually!" >&2
      echo ">>> $SERVICE is now: $(systemctl is-active "$SERVICE" 2>/dev/null || echo unknown)"
    else
      echo ">>> $SERVICE was not active before; leaving it stopped."
    fi
  }
  trap restore_engine EXIT   # runs on normal exit, error, or Ctrl-C

  if [[ "$WAS_ACTIVE" == "active" ]]; then
    echo ">>> stopping $SERVICE for a clean UID-weight read..."
    sudo systemctl stop "$SERVICE"
    sleep 2
  else
    echo ">>> $SERVICE already inactive (state=$WAS_ACTIVE); proceeding."
  fi
else
  echo ">>> DRY RUN — engine left running. Add --arm to fire (engine will be paused)."
fi

echo ">>> running canary: python3 $CANARY $*"
python3 "$CANARY" "$@"
