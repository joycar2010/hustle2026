#!/usr/bin/env bash
# dcm-coin-bridge 部署到 coin 业务机(P1.5 挂号收编,零侵入)。
# 纪律:①coin 生产服务(cex-business/cex-arb-engine)pid 前后必须一致——桥部署绝不惊动生产;
#      ②只读 DB 角色 dcm_ro 最小授权(仅 positions/engine_state SELECT);
#      ③验证=journal BRIDGE_OK + A 机 Redis 三键落地。
set -euo pipefail
HOST="${1:-57.183.43.62}"
KEY="$HOME/.ssh/cex-trading-key2.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no ec2-user@$HOST"
cd "$(dirname "$0")/.."

# 只读角色密码(本地留档,幂等复用)
SECRET_FILE="deploy/secrets/coin_ro_password"
if [ ! -f "$SECRET_FILE" ]; then
  mkdir -p deploy/secrets
  openssl rand -hex 16 > "$SECRET_FILE"
fi
ROPW=$(cat "$SECRET_FILE")

echo "== 生产服务 pid 基线 =="
BASE_PIDS=$($SSH "systemctl show -p MainPID --value cex-business cex-arb-engine | tr '\n' ' '")
echo "cex-business/cex-arb-engine: $BASE_PIDS"

echo "== 只读角色 dcm_ro(幂等) =="
$SSH "sudo -u postgres psql -d cex_trading -v ON_ERROR_STOP=1 -q" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dcm_ro') THEN
    CREATE ROLE dcm_ro LOGIN;
  END IF;
END
\$\$;
ALTER ROLE dcm_ro PASSWORD '$ROPW';
GRANT CONNECT ON DATABASE cex_trading TO dcm_ro;
GRANT USAGE ON SCHEMA public TO dcm_ro;
GRANT SELECT ON positions, engine_state TO dcm_ro;
SQL

echo "== 桥文件与 venv =="
$SSH "mkdir -p ~/dcmbridge"
scp -q -i "$KEY" -o StrictHostKeyChecking=no services/coin-bridge/app/main.py "ec2-user@$HOST:~/dcmbridge/main.py"
$SSH "umask 077; cat > ~/dcmbridge/.env" <<ENV
COIN_PG_DSN=dbname=cex_trading user=dcm_ro password=$ROPW host=127.0.0.1
DCM_REDIS_URL=redis://10.0.1.212:6379/0
COIN_ENV_PATH=/etc/systemd/system/cex-business.service
COIN_API_BASE=http://127.0.0.1:8000
DCM_ROUTE_MUTEX=1
ENV
$SSH "test -x ~/dcmbridge/venv/bin/python || python3 -m venv ~/dcmbridge/venv;
      ~/dcmbridge/venv/bin/pip -q install redis 'psycopg2-binary>=2.9' PyJWT requests >/dev/null"

echo "== systemd =="
scp -q -i "$KEY" -o StrictHostKeyChecking=no deploy/units/dcm-coin-bridge.service "ec2-user@$HOST:/tmp/"
$SSH "sudo cp /tmp/dcm-coin-bridge.service /etc/systemd/system/ && sudo systemctl daemon-reload &&
      sudo systemctl enable -q dcm-coin-bridge || true; sudo systemctl restart dcm-coin-bridge"
sleep 8

echo "== 验证 =="
$SSH "sudo journalctl -u dcm-coin-bridge -n 20 --no-pager | grep -q BRIDGE_OK" \
  || { echo "FAIL: 无 BRIDGE_OK"; $SSH "sudo journalctl -u dcm-coin-bridge -n 20 --no-pager"; exit 1; }
AFTER_PIDS=$($SSH "systemctl show -p MainPID --value cex-business cex-arb-engine | tr '\n' ' '")
if [ "$BASE_PIDS" != "$AFTER_PIDS" ]; then
  echo "FAIL: 生产服务 pid 变化! before=[$BASE_PIDS] after=[$AFTER_PIDS]"; exit 1
fi
echo "生产服务 pid 未动: $AFTER_PIDS"
echo "DEPLOY_OK dcm-coin-bridge@$HOST"
