#!/usr/bin/env bash
# Launch LIVE mode bots (REAL ORDERS, REAL MONEY).
# For paper trading, use scripts/run_paper.sh instead.
set -e
cd "$(dirname "$0")/.."

# A configured BTC service is the only process owner in the isolated test
# deployment. Read one non-secret key through dotenv; never source .env as
# shell code. The legacy path below remains unchanged for other deployments.
managed_unit=$(.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
print(os.environ.get('LIVE_WORKER_SYSTEMD_UNIT') or dotenv_values('.env').get('LIVE_WORKER_SYSTEMD_UNIT') or '')
PY
)
if [[ -n "$managed_unit" ]]; then
  if [[ "$managed_unit" != "polymarket-test-btc-live.service" ]]; then
    echo "unsupported managed BTC worker unit" >&2
    exit 2
  fi
  unit_root=$(systemctl show "$managed_unit" -p WorkingDirectory --value)
  if [[ -z "$unit_root" || "$(readlink -f "$unit_root")" != "$(pwd -P)" ]]; then
    echo "managed BTC service does not point to this release" >&2
    exit 2
  fi
  existing_main=$(systemctl show "$managed_unit" -p MainPID --value)
  for pid_file in bot.pid bot_btc.pid bot_eth.pid; do
    [[ -f "$pid_file" ]] || continue
    old_pid=$(cat "$pid_file")
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && [[ "$old_pid" != "$existing_main" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
      echo "another project worker is running; stop it before starting managed BTC" >&2
      exit 1
    fi
  done
  sudo -n systemctl start "$managed_unit"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    managed_pid=$(systemctl show "$managed_unit" -p MainPID --value)
    if systemctl is-active --quiet "$managed_unit" && [[ "$managed_pid" =~ ^[0-9]+$ ]] && [[ "$managed_pid" -gt 1 ]] \
       && [[ -f bot_btc.pid ]] && [[ "$(cat bot_btc.pid)" == "$managed_pid" ]] && ps -p "$managed_pid" >/dev/null 2>&1; then
      echo "BTC LIVE supervised worker running pid=$managed_pid unit=$managed_unit"
      exit 0
    fi
    sleep 0.3
  done
  echo "managed BTC worker did not become ready; inspect its journal" >&2
  exit 1
fi

# Refuse to launch against the current paper-tuning profile. This check is
# read-only and prevents accidentally placing near-full-balance orders.
.venv/bin/python scripts/live_preflight.py

# Confirm the signer, Deposit Wallet, chain and CLOB credentials before any
# worker is spawned. A failed verification leaves paper services untouched.
.venv/bin/python scripts/verify_setup.py

# bot.pid is used by the paper launcher and by the BTC live launcher.  Check it
# as well as the per-asset files so the UI can never start live beside a paper
# worker (which would race on the same database and wallet).
for pid_file in bot.pid bot_btc.pid bot_eth.pid; do
  if [[ -f "$pid_file" ]] && ps -p "$(cat "$pid_file")" > /dev/null 2>&1; then
    echo "bot already running pid=$(cat "$pid_file") ($pid_file)"
    echo "stop it first: scripts/stop_live.sh"
    exit 1
  fi
done

mkdir -p logs
ts=$(date +%Y%m%d_%H%M%S)
btc_log="logs/bot_btc_${ts}.log"
eth_log="logs/bot_eth_${ts}.log"

ln -sfn "bot_btc_${ts}.log" logs/bot_btc_current.log
nohup .venv/bin/python -m bot.main --live --asset BTC > "$btc_log" 2>&1 &
btc_pid=$!
echo "$btc_pid" > bot.pid
echo "$btc_pid" > bot_btc.pid
echo "live" > bot.mode
disown 2>/dev/null || true
sleep 1

if ps -p "$btc_pid" > /dev/null 2>&1; then
  echo "BTC LIVE bot started pid=$btc_pid"
  echo "  log: $btc_log"
else
  echo "FAILED to start BTC bot - see $btc_log"
  exit 1
fi

# dotenv accepts both quoted and unquoted booleans.  Accept either form so
# enabling ETH in the dashboard/config is honored by the live launcher.
if grep -Eiq '^ETH_TRADING_ENABLED="?true"?[[:space:]]*$' .env; then
  ln -sfn "bot_eth_${ts}.log" logs/bot_eth_current.log
  nohup .venv/bin/python -m bot.main --live --asset ETH > "$eth_log" 2>&1 &
  eth_pid=$!
  echo "$eth_pid" > bot_eth.pid
  disown 2>/dev/null || true
  sleep 1
  if ps -p "$eth_pid" > /dev/null 2>&1; then
    echo "ETH LIVE bot started pid=$eth_pid"
    echo "  log: $eth_log"
  else
    echo "FAILED to start ETH bot - see $eth_log"
    exit 1
  fi
else
  rm -f bot_eth.pid
  echo "ETH live disabled; set ETH_TRADING_ENABLED=true to trade ETH"
fi

echo "REAL ORDERS will be placed against your funded deposit wallet"
echo "stop: scripts/stop_live.sh"
