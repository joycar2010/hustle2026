#!/usr/bin/env python3
"""route_qualification —— 路由级真钱执行授权账(PACK-01 §11.2,LP4 C侧)。

模型:一条"路由"= (symbol, venue_long, venue_short)。路由要真钱开仓,必须持有
一份有效 ExecutionAuthorization。授权来源(authorization_basis)三类:
  · LAB_ARTIFACT   —— 由已验签 research_artifact 晋级而来(未来正式路径)
  · LEGACY_GRANDFATHERED —— 研究管线上线前已在跑的存量对,诚实标注,不假挂artifact
  · MANUAL_OVERRIDE —— mixadmin人工+Passkey强开(§11.2 L2),须留operator与理由
授权模式(mode):REPORT_ONLY(只记不控)/ADVISORY(违反告警)/ENFORCE(违反硬拦)。
LP4只落 REPORT_ONLY:建账+回填+暴露差异,绝不改变开仓行为(§21渐进)。

回填:5个存量对(ERA/ACE/GWEI/DEXE/TNSR)= LEGACY_GRANDFATHERED,
authorized_capability=OPEN_REAL_MONEY(既成事实),artifact_id=NULL,
并记 grandfathered_at + 备注"研究管线上线前存量,route级G1须补合约身份核对"。

用法:
  python3 route_qualification.py init         # 建表
  python3 route_qualification.py backfill     # 回填5存量对
  python3 route_qualification.py list
  python3 route_qualification.py check        # 对账:当前armed路由 vs 授权账,报未授权差异(REPORT_ONLY)
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

PG_DSN = os.environ.get("DCM_PG_DSN", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://10.0.1.95:6379/0")

DDL = """
CREATE TABLE IF NOT EXISTS route_qualification (
    route_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    venue_long TEXT NOT NULL,
    venue_short TEXT NOT NULL,
    authorization_basis TEXT NOT NULL
        CHECK(authorization_basis IN ('LAB_ARTIFACT','LEGACY_GRANDFATHERED','MANUAL_OVERRIDE')),
    authorized_capability TEXT NOT NULL DEFAULT 'OPEN_REAL_MONEY',
    mode TEXT NOT NULL DEFAULT 'REPORT_ONLY'
        CHECK(mode IN ('REPORT_ONLY','ADVISORY','ENFORCE')),
    artifact_id TEXT,
    subject_code TEXT,
    max_notional_usdt NUMERIC,
    authorized_by TEXT,
    authorization_reason TEXT,
    grandfathered_at BIGINT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    active BOOLEAN DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_rq_symbol ON route_qualification(symbol);
"""

# 5个存量对(方向来自 dcm:exec:manager:config 的实况:long=binance现货/short=对方合约)。
# venue以实况为准回填;此处按当前生产的主流部署(binance现货多腿 × 对手合约空腿)。
LEGACY_PAIRS = [
    ("ERAUSDT", "binance", "binance"),
    ("ACEUSDT", "binance", "binance"),
    ("GWEIUSDT", "binance", "binance"),
    ("DEXEUSDT", "binance", "binance"),
    ("TNSRUSDT", "binance", "binance"),
]


def _rid(sym, vl, vs):
    return f"rq-{sym}-{vl}-{vs}".lower()


async def _pool():
    p = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    await p.execute(DDL)
    return p


async def init():
    p = await _pool()
    print("route_qualification 表已建")
    await p.close()


def _legs_to_venues(pr: dict):
    """pairs[sym].legs = [{venue,side}]:BUY腿=venue_long,SELL腿=venue_short。"""
    vl = vs = None
    for leg in pr.get("legs", []):
        if leg.get("side") == "BUY":
            vl = leg.get("venue")
        elif leg.get("side") == "SELL":
            vs = leg.get("venue")
    return vl, vs


async def _real_venues(r, sym):
    """从 dcm:exec:manager:config 读该对真实 venue_long/venue_short(实况优先)。
    结构:pairs 是 dict{sym: {legs:[{venue,side}]}}。"""
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        pr = (cfg.get("pairs") or {}).get(sym)
        if pr:
            return _legs_to_venues(pr)
    except Exception:  # noqa: BLE001
        pass
    return None, None


async def backfill():
    p = await _pool()
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    now = int(time.time())
    for sym, vl_def, vs_def in LEGACY_PAIRS:
        vl, vs = await _real_venues(r, sym)
        vl, vs = vl or vl_def, vs or vs_def
        rid = _rid(sym, vl, vs)
        await p.execute(
            "INSERT INTO route_qualification(route_id, symbol, venue_long, venue_short, "
            "authorization_basis, authorized_capability, mode, artifact_id, subject_code, "
            "authorized_by, authorization_reason, grandfathered_at) "
            "VALUES($1,$2,$3,$4,'LEGACY_GRANDFATHERED','OPEN_REAL_MONEY','REPORT_ONLY',"
            "NULL,NULL,'system:backfill',$5,$6) "
            "ON CONFLICT (route_id) DO UPDATE SET updated_at=now(), "
            "authorization_reason=EXCLUDED.authorization_reason",
            rid, sym, vl, vs,
            "研究管线上线前存量对,既成事实授权;route级G1须补合约身份核对(同名不同物风险)",
            now)
        print(f"  回填 {rid}  basis=LEGACY_GRANDFATHERED mode=REPORT_ONLY")
    await r.aclose()
    await p.close()
    print(f"backfill: {len(LEGACY_PAIRS)}个存量对已入账")


async def list_all():
    p = await _pool()
    for row in await p.fetch(
            "SELECT route_id, symbol, venue_long, venue_short, authorization_basis, "
            "mode, authorized_capability, active FROM route_qualification "
            "ORDER BY created_at LIMIT 50"):
        print(dict(row))
    await p.close()


async def check():
    """REPORT_ONLY对账:当前armed的路由若无有效授权账 → 报UNAUTHORIZED_ROUTE(只报不拦)。"""
    p = await _pool()
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    authorized = {row["symbol"] for row in await p.fetch(
        "SELECT symbol FROM route_qualification WHERE active AND mode IN "
        "('REPORT_ONLY','ADVISORY','ENFORCE')")}
    armed = set()
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        for sym, pr in (cfg.get("pairs") or {}).items():
            if pr.get("mode") == "armed":
                armed.add(sym)
    except Exception as e:  # noqa: BLE001
        print(f"读manager config失败: {e}")
    unauth = armed - authorized
    print(f"armed路由={sorted(armed)}")
    print(f"已授权路由={sorted(authorized)}")
    if unauth:
        print(f"⚠ UNAUTHORIZED_ROUTE(REPORT_ONLY,只报不拦): {sorted(unauth)}")
    else:
        print("✓ 所有armed路由均在授权账内")
    await r.aclose()
    await p.close()


async def publish_snapshot():
    """把授权账投影到 Redis dcm:route:qualification(B端只读消费,REPORT_ONLY)。
    §控制快照统一投影:C是唯一权威写方,B/exec只读。"""
    p = await _pool()
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    rows = await p.fetch(
        "SELECT route_id, symbol, venue_long, venue_short, authorization_basis, mode, "
        "authorized_capability, max_notional_usdt, artifact_id FROM route_qualification "
        "WHERE active")
    snap = {"ts": int(time.time()), "source": "C-control", "mode": "REPORT_ONLY",
            "routes": {row["symbol"]: {
                "route_id": row["route_id"], "venue_long": row["venue_long"],
                "venue_short": row["venue_short"], "basis": row["authorization_basis"],
                "mode": row["mode"], "capability": row["authorized_capability"],
                "max_notional_usdt": float(row["max_notional_usdt"]) if row["max_notional_usdt"] else None,
                "artifact_id": row["artifact_id"]} for row in rows}}
    await r.set("dcm:route:qualification", json.dumps(snap, ensure_ascii=False))
    await r.aclose()
    await p.close()
    print(f"投影已发布 dcm:route:qualification: {len(snap['routes'])}路由 @ {snap['ts']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    fn = {"init": init, "backfill": backfill, "list": list_all, "check": check,
          "publish": publish_snapshot}.get(cmd, list_all)
    asyncio.run(fn())
