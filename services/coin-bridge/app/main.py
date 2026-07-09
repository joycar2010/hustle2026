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
import time

import psycopg2
import psycopg2.extras
import redis as redis_sync

COIN_PG_DSN = os.environ.get(
    "COIN_PG_DSN", "dbname=cex_trading user=dcm_ro host=127.0.0.1")
DCM_REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_BRIDGE_INTERVAL_SEC", "30"))

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


def main():
    r = redis_sync.from_url(DCM_REDIS_URL, decode_responses=True)
    log.info("coin-bridge up interval=%ss redis=%s", INTERVAL, DCM_REDIS_URL)
    while True:
        try:
            positions, states = fetch(COIN_PG_DSN)
            now = int(time.time())
            r.set("dcm:engine:coin:positions", json.dumps(
                {"ts": now, "source": "coin-db-bridge", "venue": "binance",
                 "count": len(positions), "positions": positions},
                default=str), ex=180)
            r.set("dcm:engine:coin:state", json.dumps(
                {"ts": now, "engine_state": states}, default=str), ex=180)
            r.set("dcm:hb:coin-bridge", json.dumps(
                {"service": "coin-bridge", "ts": now, "pid": os.getpid(),
                 "positions_open": len(positions),
                 "engine_scopes": len(states)}), ex=120)
            log.info("BRIDGE_OK positions=%d engine_scopes=%d", len(positions), len(states))
        except Exception as e:
            # 单轮失败只记日志不退出:DB 重启/网络抖动自愈;键 TTL 到期即下游可见"桥停更"
            log.warning("bridge round failed: %r", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
