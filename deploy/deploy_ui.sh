#!/usr/bin/env bash
# 推送 admin-ui/dist → C 机 ~/dexcexmix/admin-dist(gateway 托管)。带 md5 校验防缓存吞部署。
set -euo pipefail
HOST="${1:-57.181.130.126}"
KEY="$HOME/.ssh/cex-trading-key2.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$HOST"
cd "$(dirname "$0")/.."
test -f admin-ui/dist/index.html || { echo "FAIL: 先 npm run build"; exit 1; }
LOCAL_MD5=$(md5sum admin-ui/dist/index.html | awk '{print $1}')
$SSH "rm -rf ~/dexcexmix/admin-dist && mkdir -p ~/dexcexmix/admin-dist"
tar czf - -C admin-ui/dist . | $SSH "tar xzf - -C ~/dexcexmix/admin-dist"
REMOTE_MD5=$($SSH "md5sum ~/dexcexmix/admin-dist/index.html | awk '{print \$1}'")
[ "$LOCAL_MD5" = "$REMOTE_MD5" ] && echo "UI_OK index.html md5 $LOCAL_MD5 一致" || { echo "FAIL md5 不一致 local=$LOCAL_MD5 remote=$REMOTE_MD5"; exit 1; }
$SSH "ls ~/dexcexmix/admin-dist/assets | wc -l | xargs echo 'assets 文件数:'"
