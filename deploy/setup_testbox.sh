#!/usr/bin/env bash
# CrossArb P0 一键部署(Amazon Linux 2,对齐生产 OS)。
# 只装:python venv + systemd 常驻 + nginx 反代(+可选 certbot TLS)。
# 隔离硬约束:不碰任何 cex-* 服务;看板只听 127.0.0.1;不连生产 Redis/DB。
#
# 用法(在已 clone/scp 到测试机的 crossarb 目录内执行):
#   CROSSARB_DOMAIN=crossarb.hustle2026.xyz CROSSARB_TLS=1 bash deploy/setup_testbox.sh
#
# 可调环境变量:
#   CROSSARB_APP_DIR (默认 当前目录)  CROSSARB_USER (默认 ec2-user)
#   CROSSARB_DOMAIN  (默认 crossarb.hustle2026.xyz)  CROSSARB_HTTP_PORT (默认 8100)
#   CROSSARB_TLS=1 启用 certbot   CROSSARB_FORCE=1 跳过同机生产服务自检(强烈不建议)
set -euo pipefail

APP_DIR="${CROSSARB_APP_DIR:-$(pwd)}"
RUN_USER="${CROSSARB_USER:-ec2-user}"
DOMAIN="${CROSSARB_DOMAIN:-crossarb.hustle2026.xyz}"
PORT="${CROSSARB_HTTP_PORT:-8100}"
DO_TLS="${CROSSARB_TLS:-0}"

echo "[*] APP_DIR=$APP_DIR  USER=$RUN_USER  DOMAIN=$DOMAIN  PORT=$PORT  TLS=$DO_TLS"
[ -f "$APP_DIR/requirements.txt" ] || { echo "!! 请在 crossarb 项目根目录内运行本脚本"; exit 1; }

# 0) 隔离自检:绝不与生产引擎机同机部署
if systemctl list-units --type=service --all 2>/dev/null | grep -qE 'cex-(business|engine|arb-engine)'; then
  echo "!! 检测到生产 cex-* 服务在本机!CrossArb 必须部署在【独立实例】,禁止与生产同机。"
  [ "${CROSSARB_FORCE:-0}" = "1" ] || { echo "!! 如确认(不建议)设 CROSSARB_FORCE=1 重跑。"; exit 1; }
fi

# 1) 系统依赖
echo "[*] 安装系统依赖..."
sudo yum -y install python3 git >/dev/null
if ! command -v nginx >/dev/null 2>&1; then
  sudo amazon-linux-extras install -y nginx1 >/dev/null 2>&1 || sudo yum -y install nginx >/dev/null
fi
sudo systemctl enable --now nginx >/dev/null 2>&1 || true

# 2) Python venv + 依赖
echo "[*] 建 venv 并安装依赖..."
cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

# 3) 配置 + 数据目录
[ -f .env ] || { cp config.example.env .env; echo "[*] 已生成 .env(请按需改 CROSSARB_BASE_RPC 为 Alchemy/QuickNode 以避免公共 RPC 限频)"; }
mkdir -p data
sudo chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"

# 4) systemd 常驻
echo "[*] 安装 systemd 服务 crossarb-p0..."
sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@USER@#$RUN_USER#g" \
    deploy/crossarb-p0.service | sudo tee /etc/systemd/system/crossarb-p0.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now crossarb-p0

# 5) nginx 反代
echo "[*] 安装 nginx 反代 crossarb.conf..."
sed -e "s#@DOMAIN@#$DOMAIN#g" -e "s#@PORT@#$PORT#g" \
    deploy/crossarb-nginx.conf | sudo tee /etc/nginx/conf.d/crossarb.conf >/dev/null
sudo nginx -t && sudo systemctl reload nginx

# 6) 可选 TLS
if [ "$DO_TLS" = "1" ]; then
  echo "[*] 申请 TLS 证书..."
  sudo yum -y install certbot python3-certbot-nginx >/dev/null 2>&1 || {
    sudo amazon-linux-extras install -y epel >/dev/null 2>&1 || true
    sudo yum -y install certbot python3-certbot-nginx >/dev/null 2>&1 || true; }
  sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@${DOMAIN#*.}" \
    || echo "!! certbot 失败,先用 HTTP 验证,稍后手动跑 certbot。"
fi

# 7) 验证
echo "[*] 等待采集起拍并自检..."
sleep 8
echo "----- /api/health -----"
curl -s "http://127.0.0.1:$PORT/api/health" || echo "(health 未就绪,看 journalctl)"
echo; echo "----- systemd -----"
systemctl is-active crossarb-p0 && echo "crossarb-p0 已运行"
cat <<EOF

[done] 看板:        http://$DOMAIN/  （TLS 开启则 https://$DOMAIN/）
[done] 实时日志:    journalctl -u crossarb-p0 -f
[done] 采集数据:    $APP_DIR/data/ticks.csv
[done] 改市场:      编辑 $APP_DIR/markets.json(可选)后 sudo systemctl restart crossarb-p0
[note] 多市场强烈建议把 .env 的 CROSSARB_BASE_RPC 换成 Alchemy/QuickNode,
       公共 RPC 并发限频会丢采样;换后可把 CROSSARB_RPC_CONCURRENCY 调到 8。
EOF
