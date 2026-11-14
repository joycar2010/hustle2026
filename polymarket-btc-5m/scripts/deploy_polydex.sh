#!/usr/bin/env bash
# Deploy P0 fix to PolyDex EC2 and restart A/B paper + dashboard.
# Usage:
#   PEM=/path/to/HustleNew.pem HOST=ec2-user@18.179.50.168 bash scripts/deploy_polydex.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PEM="${PEM:?set PEM=...}"
HOST="${HOST:-ec2-user@18.179.50.168}"
REMOTE_DIR="${REMOTE_DIR:-/opt/polymarket-btc-5m}"

chmod 400 "$PEM"
ssh -i "$PEM" -o StrictHostKeyChecking=accept-new "$HOST" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \"\$USER:\$USER\" '$REMOTE_DIR'"
rsync -az --delete \
  --exclude '.venv' --exclude 'data/*.db' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.egg-info' \
  -e "ssh -i $PEM -o StrictHostKeyChecking=accept-new" \
  "$ROOT/" "$HOST:$REMOTE_DIR/"

ssh -i "$PEM" -o StrictHostKeyChecking=accept-new "$HOST" \
  env REMOTE_DIR="$REMOTE_DIR" bash -s <<'EOF'
set -euo pipefail
cd "$REMOTE_DIR"
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
[[ -f .env ]] || cp .env.example .env
# Upsert P0 keys
python3 - <<'PY'
from pathlib import Path
p = Path(".env")
text = p.read_text() if p.exists() else ""
updates = {
    "MAX_ENTRY_PRICE": "0.88",
    "LATE_EDGE_HARD_BAN_PRICE": "0.90",
    "MIN_NET_EDGE": "0.08",
    "CONFIRM_CHECKS": "3",
    "UP_MIN_DELTA_USD": "25",
    "DOWN_MAX_DELTA_USD": "-25",
    "MAKER_PAIR_COST_MAX": "0.97",
    "MAKER_STOP_BEFORE_END_SEC": "60",
    "MAKER_TOUCH_FILL_SEC": "12",
    "MAKER_MAX_IMBALANCE_SHARES": "10",
    "MAKER_ALLOW_CROSSED_FILLS": "false",
    "MAKER_FLATTEN_RESIDUAL": "true",
}
lines = text.splitlines()
keys = set()
out = []
for line in lines:
    if not line or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        keys.add(k)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in keys:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n")
print("env upserted", sorted(updates))
PY

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/btc5m-a.service" <<UNIT
[Unit]
Description=BTC5m Paper A late_edge
After=network.target
[Service]
WorkingDirectory=$REMOTE_DIR
Environment=MODE=late_edge
ExecStart=$REMOTE_DIR/.venv/bin/python -m btc5m --mode late_edge
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
UNIT
cat > "$HOME/.config/systemd/user/btc5m-b.service" <<UNIT
[Unit]
Description=BTC5m Paper B maker
After=network.target
[Service]
WorkingDirectory=$REMOTE_DIR
Environment=MODE=maker
ExecStart=$REMOTE_DIR/.venv/bin/python -m btc5m --mode maker
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
UNIT
cat > "$HOME/.config/systemd/user/btc5m-dash.service" <<UNIT
[Unit]
Description=BTC5m Paper Dashboard API
After=network.target
[Service]
WorkingDirectory=$REMOTE_DIR
Environment=DASHBOARD_PORT=8088
ExecStart=$REMOTE_DIR/.venv/bin/python -m btc5m dashboard
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now btc5m-a.service btc5m-b.service btc5m-dash.service
systemctl --user restart btc5m-a.service btc5m-b.service btc5m-dash.service
systemctl --user --no-pager --full status btc5m-a.service btc5m-b.service btc5m-dash.service | sed -n '1,120p'
EOF

echo "Deployed to $HOST:$REMOTE_DIR"
echo "Ensure nginx proxies /api to 127.0.0.1:8088"
