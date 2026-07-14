"""G2 四象限故障演练(合成注入)——交易可用性 × 提现可用性 的策略响应验证。

在 Redis **DB9**(隔离库,绝不碰生产 DB0)注入合成的账户快照/提现健康键,
调用真 policy.compute_and_publish(pool=None)走生产同一条代码路径,断言逐象限模式/能力位/NAV折价:

  Q1 交易OK  + 提现OK   → NORMAL(haircut 0)
  Q2 交易OK  + 提现冻结  → REDUCE_ONLY(提现pending>24h;haircut 30%)
  Q3 交易受限 + 提现OK   → NO_NEW_RISK(HARD -2015;haircut 10%)
  Q4 交易受限 + 提现冻结  → REDUCE_ONLY(取更严格;haircut 30%)
  Q5 提现连败≥2         → NO_NEW_RISK(平台限制嫌疑)

用法(C 机):
  set -a; . ~/dexcexmix/.env; set +a
  ~/dexcexmix/venv/bin/python ~/dexcexmix/src/services/risk-ledger/drill_quadrant.py
"""
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

import redis.asyncio as aioredis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
from policy import compute_and_publish  # noqa: E402

VENUE = "binance"
DRILL_DB = 9


def _drill_url() -> str:
    base = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
    p = urlparse(base)
    return f"{p.scheme}://{p.netloc}/{DRILL_DB}"


async def _inject(r, trading_ok: bool, wd: dict | None):
    snap = ({"ok": True, "equity_usdt": 100.0, "positions": {}, "pos_detail": {}}
            if trading_ok else
            {"ok": False, "err": "code=-2015 Invalid API-key, IP, or permissions for action",
             "equity_usdt": 100.0})
    await r.set(f"dcm:account:{VENUE}", json.dumps(snap), ex=120)
    if wd is None:
        await r.delete(f"dcm:risk:withdrawal:{VENUE}")
    else:
        await r.set(f"dcm:risk:withdrawal:{VENUE}",
                    json.dumps({"ts": int(time.time()), "venue": VENUE, "pending_count": 1,
                                "p50_sec": None, "p95_sec": None, "sample_n": 0,
                                "last_success_at": 0, **wd}), ex=120)


WD_OK = {"oldest_pending_age_sec": 0, "recent_failures": 0}
WD_FROZEN = {"oldest_pending_age_sec": 30 * 3600, "recent_failures": 0}   # pending 30h > 24h 阈
WD_FAILS = {"oldest_pending_age_sec": 0, "recent_failures": 2}

CASES = [
    ("Q1 交易OK+提现OK",   True,  WD_OK,     "NORMAL",       0.00, {"CAN_OPEN": True,  "CAN_REDUCE": True}),
    ("Q2 交易OK+提现冻结", True,  WD_FROZEN, "REDUCE_ONLY",  0.30, {"CAN_OPEN": False, "CAN_REDUCE": True}),
    ("Q3 交易受限+提现OK", False, WD_OK,     "NO_NEW_RISK",  0.10, {"CAN_OPEN": False, "CAN_REDUCE": True}),
    ("Q4 交易受限+提现冻结", False, WD_FROZEN, "REDUCE_ONLY", 0.30, {"CAN_OPEN": False, "CAN_REDUCE": True}),
    ("Q5 提现连败≥2",      True,  WD_FAILS,  "NO_NEW_RISK",  0.10, {"CAN_OPEN": False, "CAN_REDUCE": True}),
]


async def main():
    url = _drill_url()
    assert url.endswith(f"/{DRILL_DB}"), f"演练必须在 DB{DRILL_DB}: {url}"
    r = aioredis.from_url(url, decode_responses=True)
    await r.flushdb()   # DB9 专用演练库,清场
    passed = failed = 0
    for name, trading_ok, wd, want_mode, want_hc, want_caps in CASES:
        await _inject(r, trading_ok, wd)
        pol = await compute_and_publish(None, r)
        vd = pol["venues"][VENUE]
        errs = []
        if vd["mode"] != want_mode:
            errs.append(f"mode={vd['mode']} 期望{want_mode}")
        if abs(float(vd.get("haircut_pct", -1)) - want_hc) > 1e-9:
            errs.append(f"haircut={vd.get('haircut_pct')} 期望{want_hc}")
        for cap, want in want_caps.items():
            if bool(vd["capabilities"].get(cap)) is not want:
                errs.append(f"{cap}={vd['capabilities'].get(cap)} 期望{want}")
        want_trapped = round(100.0 * want_hc, 2)
        got_trapped = float(vd.get("trapped_usdt") or 0)
        if abs(got_trapped - want_trapped) > 0.01:
            errs.append(f"trapped={got_trapped} 期望{want_trapped}")
        nav = pol.get("nav") or {}
        if want_hc > 0 and float(nav.get("trapped_by_venue", {}).get(VENUE) or 0) <= 0:
            errs.append("nav.trapped_by_venue 缺该venue")
        if errs:
            failed += 1
            print(f"FAIL {name}: {'; '.join(errs)}  reason={vd.get('reason')}")
        else:
            passed += 1
            print(f"PASS {name}: mode={vd['mode']} haircut={vd['haircut_pct']} "
                  f"trapped={vd['trapped_usdt']}U reason={str(vd.get('reason'))[:80]}")
    await r.flushdb()
    await r.aclose()
    print(f"DRILL_{'OK' if failed == 0 else 'FAIL'} passed={passed} failed={failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
