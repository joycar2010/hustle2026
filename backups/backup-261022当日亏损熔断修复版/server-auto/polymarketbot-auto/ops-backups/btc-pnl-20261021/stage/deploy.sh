#!/usr/bin/env bash
set -euo pipefail
app_root=/home/ec2-user/polymarketbot-auto
backup_dir="$app_root/ops-backups/btc-pnl-20261021"
release_dir="$backup_dir/stage"
webroot=/var/www/polyauto.hustle2026.xyz
test -s "$release_dir/ui/dist/index.html"
# Abort if another deployment changed any source while this release was built.
cmp "$app_root/server/dashboard.py" "$backup_dir/source/dashboard.py"
cmp "$app_root/ui/src/App.tsx" "$backup_dir/source/App.tsx"
cmp "$app_root/ui/src/types.ts" "$backup_dir/source/types.ts"
systemctl show polymarket-auto-btc-paper.service polymarket-auto-openclaw-paper.service --property=Id,MainPID,ExecMainStartTimestamp,ActiveState > "$backup_dir/workers-before.txt"
sha256sum "$app_root/bot/main.py" "$app_root/bot/store.py" "$app_root/bot/strategy.py" "$app_root/bot/risk.py" "$app_root/bot/orders.py" > "$backup_dir/trading-before.sha256"
install -m 644 "$release_dir/dashboard.py" "$app_root/server/dashboard.py.next"
mv "$app_root/server/dashboard.py.next" "$app_root/server/dashboard.py"
restore_backend() {
    cp -a "$backup_dir/source/dashboard.py" "$app_root/server/dashboard.py"
    sudo systemctl restart polymarket-auto-dashboard.service
}
trap restore_backend ERR
sudo systemctl restart polymarket-auto-dashboard.service
"$app_root/.venv/bin/python" - <<'PY'
import json, time, urllib.request
for attempt in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8887/api/state', timeout=5) as response:
            data = json.load(response)
        assert 'BTC' in data['mode_split']['paper']['cumulative_by_asset']
        assert data['mode_split']['paper']['cumulative_asof_ts'] > 0
        print('Dashboard API cumulative BTC contract ready.')
        break
    except Exception:
        if attempt == 29: raise
        time.sleep(.5)
PY
cp "$release_dir/App.tsx" "$release_dir/types.ts" "$release_dir/pnl.ts" "$app_root/ui/src/"
cp "$release_dir/test_btc_pnl_contract.py" "$app_root/tests/test_btc_pnl_contract.py"
# Additive sync keeps every historical dist asset. Publish HTML last.
rsync -a --exclude=index.html "$release_dir/ui/dist/" "$app_root/ui/dist/"
install -m 644 "$release_dir/ui/dist/index.html" "$app_root/ui/dist/index.html.next"
mv "$app_root/ui/dist/index.html.next" "$app_root/ui/dist/index.html"
sudo rsync -a --exclude=index.html "$release_dir/ui/dist/" "$webroot/"
sudo install -m 644 "$release_dir/ui/dist/index.html" "$webroot/index.html.next"
sudo mv "$webroot/index.html.next" "$webroot/index.html"
trap - ERR
sha256sum -c "$backup_dir/trading-before.sha256"
systemctl show polymarket-auto-btc-paper.service polymarket-auto-openclaw-paper.service --property=Id,MainPID,ExecMainStartTimestamp,ActiveState > "$backup_dir/workers-after.txt"
cmp "$backup_dir/workers-before.txt" "$backup_dir/workers-after.txt"
echo 'Deployment complete; trading source and worker processes unchanged.'
