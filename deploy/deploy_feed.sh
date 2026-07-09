#!/usr/bin/env bash
# dcm-feed 构建+部署(A 机数据面)。目标机 x86 原生构建免交叉编译;源=本仓整树推送(单一真源)。
# 验证纪律:新 pid + journal 连接日志 + 心跳键 + 行情哈希在涨。
set -euo pipefail
HOST="${1:-52.193.224.137}"
KEY="$HOME/.ssh/cex-trading-key2.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$HOST"
cd "$(dirname "$0")/.."

# 工具链(一次性幂等):gcc 链接器 + ec2-user 级 rustup minimal
$SSH 'command -v cc >/dev/null || sudo dnf -y -q install gcc;
      test -x ~/.cargo/bin/cargo || (curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null 2>&1)'

OLD_PID=$($SSH "systemctl show -p MainPID --value dcm-feed-cex 2>/dev/null" || echo 0)

$SSH "mkdir -p ~/dexcexmix/src ~/dexcexmix/bin"
tar czf - --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    --exclude='deploy/secrets' --exclude='target' \
    packages services deploy | $SSH "tar xzf - -C ~/dexcexmix/src"

echo "== cargo build (目标机原生) =="
$SSH "cd ~/dexcexmix/src/services/feed-cex && ~/.cargo/bin/cargo build --release 2>&1 | tail -4 &&
      cp target/release/dcm-feed ~/dexcexmix/bin/dcm-feed.new &&
      mv ~/dexcexmix/bin/dcm-feed.new ~/dexcexmix/bin/dcm-feed"

$SSH "sudo cp ~/dexcexmix/src/deploy/units/dcm-feed-cex.service /etc/systemd/system/ &&
      sudo systemctl daemon-reload && sudo systemctl enable -q dcm-feed-cex || true;
      sudo systemctl restart dcm-feed-cex"
sleep 6

NEW_PID=$($SSH "systemctl show -p MainPID --value dcm-feed-cex")
if [ -z "$NEW_PID" ] || [ "$NEW_PID" = "0" ] || [ "$NEW_PID" = "$OLD_PID" ]; then
  echo "FAIL: pid 未更新 (old=$OLD_PID new=$NEW_PID)"
  $SSH "sudo journalctl -u dcm-feed-cex -n 30 --no-pager"
  exit 1
fi
$SSH "sudo journalctl -u dcm-feed-cex -n 50 --no-pager | grep -q 'WS connected'" \
  || { echo "FAIL: journal 无 WS connected"; $SSH "sudo journalctl -u dcm-feed-cex -n 30 --no-pager"; exit 1; }
echo "DEPLOY_OK dcm-feed-cex@$HOST pid $OLD_PID -> $NEW_PID (心跳/哈希需再等一个30s窗口验证)"
