#!/usr/bin/env bash
# Stop one live worker without touching unrelated asset workers.
set -euo pipefail
cd "$(dirname "$0")/.."
asset="${1:?asset required}"
case "$asset" in
  BTC) pid_file=bot_btc.pid ;;
  ETH) pid_file=bot_eth.pid ;;
  ALL) pid_file="" ;;
  *) echo "unsupported asset: $asset" >&2; exit 2 ;;
esac
managed_unit=$(.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
print(os.environ.get('LIVE_WORKER_SYSTEMD_UNIT') or dotenv_values('.env').get('LIVE_WORKER_SYSTEMD_UNIT') or '')
PY
)
if [[ -n "$managed_unit" ]]; then
  if [[ "$managed_unit" != "polymarket-test-btc-live.service" || "$asset" == "ETH" ]]; then
    echo "managed worker controller is restricted to polytest BTC" >&2
    exit 2
  fi
  unit_root=$(systemctl show "$managed_unit" -p WorkingDirectory --value)
  if [[ -z "$unit_root" || "$(readlink -f "$unit_root")" != "$(pwd -P)" ]]; then
    echo "managed BTC service does not point to this release" >&2
    exit 2
  fi
  sudo -n systemctl stop "$managed_unit"
  echo "BTC LIVE supervised worker stopped unit=$managed_unit"
  exit 0
fi
stopped=0
if [[ "$asset" == "ALL" ]]; then
  "$0" BTC || true
  "$0" ETH || true
  exit 0
fi
if [[ -f "$pid_file" ]]; then
  pid=$(cat "$pid_file")
  if ps -p "$pid" >/dev/null 2>&1; then
    kill "$pid"
    for _ in 1 2 3 4 5; do
      ps -p "$pid" >/dev/null 2>&1 || break
      sleep 1
    done
    if ps -p "$pid" >/dev/null 2>&1; then kill -9 "$pid"; fi
    echo "stopped $pid_file pid=$pid"
    stopped=1
  fi
  rm -f "$pid_file"
fi
if [[ "$asset" == "BTC" && -f bot.pid ]]; then rm -f bot.pid; fi
if [[ "$stopped" == "0" ]]; then echo "no $asset live worker found"; fi
if [[ ! -f bot_btc.pid && ! -f bot_eth.pid ]]; then rm -f bot.mode; fi
