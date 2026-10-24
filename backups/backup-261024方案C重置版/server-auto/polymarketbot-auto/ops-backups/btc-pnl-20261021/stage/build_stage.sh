#!/usr/bin/env bash
set -euo pipefail
app_root=/home/ec2-user/polymarketbot-auto
release_dir="$app_root/ops-backups/btc-pnl-20261021/stage"
mkdir "$release_dir/ui"
cp -a "$app_root/ui/src" "$release_dir/ui/"
if [ -d "$app_root/ui/public" ]; then cp -a "$app_root/ui/public" "$release_dir/ui/"; fi
cp -a "$app_root"/ui/package*.json "$app_root"/ui/tsconfig*.json "$app_root/ui/vite.config.ts" "$app_root/ui/index.html" "$release_dir/ui/"
for env_file in "$app_root"/ui/.env*; do
    if [ -f "$env_file" ]; then cp -a "$env_file" "$release_dir/ui/"; fi
done
ln -s "$app_root/ui/node_modules" "$release_dir/ui/node_modules"
cp "$release_dir/App.tsx" "$release_dir/types.ts" "$release_dir/pnl.ts" "$release_dir/ui/src/"
cd "$release_dir/ui"
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
