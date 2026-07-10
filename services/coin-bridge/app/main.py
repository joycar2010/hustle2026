"""dcm-coin-bridge:coin 挂号收编旁车(P1.5,零侵入)。

部署在 coin 业务机,用**只读 DB 账号(dcm_ro)**读 positions/engine_state,
按 DexCexMix 总线契约写到 A 机 Redis。coin 现有两个服务(cex-business/cex-arb-engine)
一行代码不动:桥挂了 coin 无感,coin 挂了桥如实上报(engine_state.last_heartbeat 停走)。

键契约(risk-ledger 消费):
- dcm:hb:coin-bridge          桥自身心跳(EX 120)——只证明桥活,不假冒引擎活性
- dcm:engine:coin:state       engine_state 全行(EX 180)——引擎活性由消费者按 last_heartbeat 判断
- dcm:engine:coin:positions   非终态仓位原始字段快照(EX 180)——"coin 引擎声称的在管仓位"(意图账),
                              实盘真相由 risk-ledger 直拉交易所只读 API 另行核对,绝不采信单侧

字段按 DB 原样透传(Decimal→str 保精度),数据面纪律:只采集归一不判断。
兼容 py3.7+(coin 机 Python 版本未知,不用新语法)。
"""
import json
import logging
import os
import re
import time

import psycopg2
import psycopg2.extras
import redis as redis_sync

COIN_PG_DSN = os.environ.get(
    "COIN_PG_DSN", "dbname=cex_trading user=dcm_ro host=127.0.0.1")
DCM_REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_BRIDGE_INTERVAL_SEC", "30"))
# 代理式操作合并(绞杀者第二步):gateway 把审计过的命令写 dcm:coin:cmd,本桥消费→
# 本地铸 JWT(密钥永不离开 coin 机)→调 coin localhost FastAPI(coin 逻辑仍权威)
# 注:coin 的 CEX_JWT_SECRET 配在 systemd unit 的 Environment= 行(非 .env),unit 644 可读
COIN_ENV = os.environ.get("COIN_ENV_PATH", "/etc/systemd/system/cex-business.service")
COIN_API = os.environ.get("COIN_API_BASE", "http://127.0.0.1:8000")
CMD_QUEUE = "dcm:coin:cmd"
# 白名单:action → (method, path)。v1 只放最安全的引擎启停;扩 manual-close 等须逐个评审
# engine_status 为零副作用只读探针:验证 JWT铸造→coin鉴权→执行→回执 全链路,不动生产状态
CMD_WHITELIST = {
    "engine_status": ("GET", "/api/engine/workers/status", {}),
    "engine_start": ("POST", "/api/engine/workers/start", {}),
    "engine_stop": ("POST", "/api/engine/workers/stop", {}),
}


def _coin_jwt_secret() -> str | None:
    try:
        m = re.search(r"CEX_JWT_SECRET=([^\s\"']+)", open(COIN_ENV).read())
        return m.group(1) if m else None
    except Exception as e:
        log.warning("read coin jwt secret failed: %r", e)
        return None


def _mint_jwt(secret: str, user_id: int = 1) -> str:
    import datetime
    import jwt
    payload = {"sub": "dcm-proxy", "user_id": user_id, "role": "SUPER_ADMIN",
               "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)}
    return jwt.encode(payload, secret, algorithm="HS256")


def _exec_command(cmd: dict) -> dict:
    """执行一条白名单命令,调 coin 本地 FastAPI。返回结果 dict。"""
    import requests
    action = cmd.get("action")
    if action not in CMD_WHITELIST:
        return {"ok": False, "err": f"action 不在白名单: {action}"}
    secret = _coin_jwt_secret()
    if not secret:
        return {"ok": False, "err": "coin jwt secret 不可读"}
    method, path, base_body = CMD_WHITELIST[action]
    body = {**base_body, **(cmd.get("params") or {})}
    try:
        tok = _mint_jwt(secret, int(cmd.get("user_id", 1)))
        resp = requests.request(method, f"{COIN_API}{path}", json=body,
                                headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        return {"ok": resp.status_code < 400, "status": resp.status_code,
                "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]}
    except Exception as e:
        return {"ok": False, "err": repr(e)[:200]}


def consume_commands(r):
    """消费 dcm:coin:cmd(lpop),执行并把结果写 dcm:coin:cmd:result:{id}(EX60)。"""
    for _ in range(20):  # 每轮最多处理 20 条防饥饿
        raw = r.lpop(CMD_QUEUE)
        if not raw:
            break
        try:
            cmd = json.loads(raw)
        except Exception:
            continue
        cid = cmd.get("id", "")
        log.info("COIN_CMD exec id=%s action=%s by=%s", cid, cmd.get("action"), cmd.get("operator"))
        result = _exec_command(cmd)
        result["ts"] = int(time.time())
        result["action"] = cmd.get("action")
        if cid:
            r.set(f"dcm:coin:cmd:result:{cid}", json.dumps(result, default=str), ex=60)
        log.info("COIN_CMD done id=%s ok=%s", cid, result.get("ok"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coin-bridge")

SQL_POSITIONS = """
SELECT id, sub_account_id, user_id, symbol, base_asset, status, hedge_account,
       borrow_qty, spot_sell_qty, spot_buy_qty, futures_long_qty, repay_qty,
       open_usdt_amount,
       EXTRACT(EPOCH FROM opened_at)::bigint  AS opened_ts,
       EXTRACT(EPOCH FROM updated_at)::bigint AS updated_ts
FROM positions
WHERE status NOT IN ('CLOSED', 'FAILED')
ORDER BY id
"""

SQL_ENGINE_STATE = """
SELECT scope, status, pid, user_id, active_positions, total_cycles,
       EXTRACT(EPOCH FROM last_heartbeat)::bigint AS heartbeat_ts,
       EXTRACT(EPOCH FROM updated_at)::bigint     AS updated_ts
FROM engine_state
"""


def fetch(dsn):
    conn = psycopg2.connect(dsn)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(SQL_POSITIONS)
            positions = [dict(r) for r in cur.fetchall()]
            cur.execute(SQL_ENGINE_STATE)
            states = [dict(r) for r in cur.fetchall()]
        return positions, states
    finally:
        conn.close()


def publish_state(r):
    positions, states = fetch(COIN_PG_DSN)
    now = int(time.time())
    r.set("dcm:engine:coin:positions", json.dumps(
        {"ts": now, "source": "coin-db-bridge", "venue": "binance",
         "count": len(positions), "positions": positions}, default=str), ex=180)
    r.set("dcm:engine:coin:state", json.dumps(
        {"ts": now, "engine_state": states}, default=str), ex=180)
    r.set("dcm:hb:coin-bridge", json.dumps(
        {"service": "coin-bridge", "ts": now, "pid": os.getpid(),
         "positions_open": len(positions), "engine_scopes": len(states),
         "proxy": "on"}), ex=120)
    log.info("BRIDGE_OK positions=%d engine_scopes=%d", len(positions), len(states))


def main():
    r = redis_sync.from_url(DCM_REDIS_URL, decode_responses=True)
    log.info("coin-bridge up interval=%ss redis=%s proxy_whitelist=%s",
             INTERVAL, DCM_REDIS_URL, list(CMD_WHITELIST))
    last_state = 0.0
    while True:
        try:
            consume_commands(r)              # 命令消费(~2s 响应)
            if time.time() - last_state >= INTERVAL:
                publish_state(r)             # 状态发布(INTERVAL)
                last_state = time.time()
        except Exception as e:
            log.warning("bridge round failed: %r", e)
        time.sleep(2)


if __name__ == "__main__":
    main()
