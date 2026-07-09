#!/usr/bin/env bash
# DexCexMix 部署:tar 推送 → venv 安装 → systemd 重启 → 真验证(新pid + 真HTTP断言)。
# 用法: deploy.sh <service> <host> [health_port|none]
#   health_port=none → 无HTTP服务(后台任务型),验证改为 journal 内出现 SYNC_OK/started 标记。
# 纪律(coin 部署手册):绝不以"命令跑完"为成功;必须新 pid + 真验证。
set -euo pipefail
SVC="${1:?service}"; HOST="${2:?host}"; PORT="${3:-8000}"
KEY="$HOME/.ssh/cex-trading-key2.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$HOST"
cd "$(dirname "$0")/.."

OLD_PID=$($SSH "systemctl show -p MainPID --value dcm-$SVC 2>/dev/null" || echo 0)

$SSH "mkdir -p ~/dexcexmix/src"
tar czf - --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='deploy/secrets' \
    packages services deploy | $SSH "tar xzf - -C ~/dexcexmix/src"

$SSH "test -x ~/dexcexmix/venv/bin/python || python3.11 -m venv ~/dexcexmix/venv;
      ~/dexcexmix/venv/bin/pip -q install -U pip >/dev/null;
      ~/dexcexmix/venv/bin/pip -q install -e ~/dexcexmix/src/packages/dcm-common -r ~/dexcexmix/src/services/$SVC/requirements.txt"

$SSH "sudo cp ~/dexcexmix/src/deploy/units/dcm-$SVC.service /etc/systemd/system/ &&
      sudo systemctl daemon-reload && sudo systemctl enable dcm-$SVC -q;
      sudo systemctl restart dcm-$SVC"
sleep 3

NEW_PID=$($SSH "systemctl show -p MainPID --value dcm-$SVC")
if [ -z "$NEW_PID" ] || [ "$NEW_PID" = "0" ] || [ "$NEW_PID" = "$OLD_PID" ]; then
  echo "FAIL: pid 未更新 (old=$OLD_PID new=$NEW_PID)"; $SSH "sudo journalctl -u dcm-$SVC -n 20 --no-pager"; exit 1
fi
if [ "$PORT" = "none" ]; then
  sleep 25
  $SSH "sudo journalctl -u dcm-$SVC -n 80 --no-pager | grep -qE 'SYNC_OK|started|up '" \
    || { echo "FAIL: journal 无成功标记"; $SSH "sudo journalctl -u dcm-$SVC -n 30 --no-pager"; exit 1; }
else
  $SSH "curl -sf -m 5 http://127.0.0.1:$PORT/healthz | grep -q '\"service\"'" \
    || { echo "FAIL: /healthz body 无 service 字段"; $SSH "sudo journalctl -u dcm-$SVC -n 20 --no-pager"; exit 1; }
  $SSH "curl -sfI -m 5 http://127.0.0.1:$PORT/healthz | grep -qi 'content-type: application/json'" \
    || { echo "FAIL: content-type 非 json"; exit 1; }
fi
echo "DEPLOY_OK dcm-$SVC@$HOST pid $OLD_PID -> $NEW_PID"
