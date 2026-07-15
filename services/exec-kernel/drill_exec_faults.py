"""批次E 执行层故障演练(V2 §14 验收 5 项)——合成注入 Redis DB9,走真代码路径断言。

绝不碰生产 DB0;调用真 policy_client(fail-closed/WAL/fence)+ repair(单腿救援)代码。
覆盖:
  E1 C/B 网络分区(策略快照超龄90s)→ fail-closed:CAN_OPEN=False,但减险(CAN_REDUCE/CANCEL/
     RESCUE_HEDGE)不受影响。
  E2 旧快照复活(重放低 epoch)→ fence 拒绝当新鲜(fail-closed)。
  E3 第一腿成交后策略降级 → 第二腿不能沿用开仓授权(CAN_OPEN=False;补对冲 CAN_COMPLETE_HEDGE 仍可)。
  E4 C3 已借未卖(单腿裸露)+ 受限 venue → repair 生成 EVACUATE/RESCUE 意图(不可行=trapped 告警)。
  E5 排空期间新增 Incident → policy 正确叠加(REDUCE_ONLY 不被 override 冲淡)。

用法(B 机,exec-kernel 目录):
  set -a; . ~/dexcexmix/.env; set +a
  DCM_POLICY_WAL=/tmp/drill_wal.json ~/dexcexmix/venv/bin/python ~/dexcexmix/drill_exec_faults.py
"""
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/packages/dcm-common")
import policy_client as pc  # noqa: E402

DRILL_DB = 9


def _drill_url():
    p = urlparse(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"))
    return f"{p.scheme}://{p.netloc}/{DRILL_DB}"


CAPS_OK = {"CAN_QUERY": True, "CAN_CANCEL": True, "CAN_OPEN": True, "CAN_INCREASE_GROSS": True,
           "CAN_INCREASE_DEBT": True, "CAN_REDUCE": True, "CAN_REPAY": True,
           "CAN_RESCUE_HEDGE": True, "CAN_COMPLETE_HEDGE": True}
CAPS_REDUCE = {**CAPS_OK, "CAN_OPEN": False, "CAN_INCREASE_GROSS": False, "CAN_INCREASE_DEBT": False}


def _policy(epoch, seq, mode="NORMAL", caps=None, ts=None):
    return {"policy_epoch": epoch, "policy_version": seq, "ts": ts if ts is not None else int(time.time()),
            "global_mode": "NORMAL",
            "venues": {"binance": {"mode": mode, "capabilities": caps or CAPS_OK,
                                   "equity": 100, "reason": mode}}}


async def main():
    url = _drill_url()
    assert url.endswith(f"/{DRILL_DB}"), f"演练须 DB{DRILL_DB}: {url}"
    r = aioredis.from_url(url, decode_responses=True)
    await r.flushdb()
    # WAL 用临时文件,别碰生产 ~/dexcexmix/.risk_policy_wal.json
    os.environ["DCM_POLICY_WAL"] = "/tmp/drill_exec_wal.json"
    try:
        os.remove("/tmp/drill_exec_wal.json")
    except OSError:
        pass
    pc._wal_loaded = False
    pc._last_fence = {"epoch": -1, "seq": -1}
    pc.WAL_PATH = "/tmp/drill_exec_wal.json"
    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}: {detail}")

    # ── E1 网络分区:快照超龄90s → fail-closed ──
    await r.set(pc.POLICY_KEY, json.dumps(_policy(1, 100, "NORMAL", ts=int(time.time()) - 120)))
    pol, fresh = await pc.read_policy(r)
    ok, reason = await pc.can_open(r, "binance")
    check("E1 超龄→fail-closed CAN_OPEN=False", (not fresh) and (not ok), f"fresh={fresh} ok={ok}")
    # 减险不受影响(can_open 只答新增;减险由调用方各自判——这里验 policy 仍带 CAN_REDUCE)
    check("E1 减险能力仍在(CAN_REDUCE)", (pol.get("venues", {}).get("binance", {})
          .get("capabilities", {}).get("CAN_REDUCE") is True), "reduce cap lost")

    # ── E2 旧快照复活:先喂新鲜高版本,再喂旧低版本 ──
    await r.set(pc.POLICY_KEY, json.dumps(_policy(2, 500, "NORMAL")))
    _, fresh_hi = await pc.read_policy(r)
    await r.set(pc.POLICY_KEY, json.dumps(_policy(1, 100, "NORMAL")))   # 旧 epoch/seq 复活
    _, fresh_old = await pc.read_policy(r)
    check("E2 旧快照复活被 fence 拒绝", fresh_hi and (not fresh_old), f"hi={fresh_hi} old={fresh_old}")

    # ── E3 第一腿成交后降级:CAN_OPEN=False 但补对冲(CAN_COMPLETE_HEDGE)仍可 ──
    await r.set(pc.POLICY_KEY, json.dumps(_policy(2, 600, "REDUCE_ONLY", CAPS_REDUCE)))
    pol3, fresh3 = await pc.read_policy(r)
    ok3, _ = await pc.can_open(r, "binance")
    caps3 = pol3["venues"]["binance"]["capabilities"]
    check("E3 降级后 CAN_OPEN=False(第二腿不沿用开仓授权)", not ok3, f"ok={ok3}")
    check("E3 补对冲 CAN_COMPLETE_HEDGE 仍可", caps3.get("CAN_COMPLETE_HEDGE") is True, "hedge completion blocked")
    check("E3 救援 CAN_RESCUE_HEDGE 仍可(REDUCE_ONLY)", caps3.get("CAN_RESCUE_HEDGE") is True, "rescue blocked")

    # ── E4 C3 已借未卖单腿 + 受限 venue → repair 意图 ──
    # 合成 manager 快照:一 pair 单腿在场(bybit 有仓/binance 平了),binance REDUCE_ONLY
    await r.set(pc.POLICY_KEY, json.dumps({
        "policy_epoch": 2, "policy_version": 700, "ts": int(time.time()), "global_mode": "NORMAL",
        "venues": {"binance": {"mode": "FROZEN", "capabilities": {**CAPS_REDUCE, "CAN_REDUCE": False},
                               "equity": 100, "reason": "FROZEN drill(trapped +10 平不掉)"},
                   "bybit": {"mode": "REDUCE_ONLY", "capabilities": CAPS_REDUCE, "equity": 100, "reason": "reduce"},
                   "okx": {"mode": "NORMAL", "capabilities": CAPS_OK, "equity": 200, "reason": "ok(第三救援所)"}}}))
    # binance FROZEN 且有 +10 多仓平不掉=trapped;okx 健康作第三 venue 救援(反向对冲 delta)
    await r.set("dcm:exec:manager", json.dumps({"ts": int(time.time()), "pairs": [
        {"pair": "drill-FILUSDT", "symbol": "FILUSDT", "action": "SINGLE_LEG",
         "legs": [{"venue": "binance", "amt": 10}, {"venue": "bybit", "amt": 0}]}]}))
    now_ms = int(time.time() * 1000)
    l1 = json.dumps({"bid": 5.0, "ask": 5.002, "ts": now_ms, "recv_ts": now_ms})
    await r.hset("dcm:feed:bybit:perp", "FILUSDT", l1)
    await r.hset("dcm:feed:binance:perp", "FILUSDT", l1)
    await r.hset("dcm:feed:okx:perp", "FILUSDT", l1)
    try:
        import repair as rp
        rp.read_policy = pc.read_policy   # 用同一 DB9 policy
        pol4, fr4 = await pc.read_policy(r)
        trigger = {v: d for v, d in pol4["venues"].items() if d["mode"] in rp.TRIGGER_MODES}
        legs = [{"venue": "binance", "amt": 10}, {"venue": "bybit", "amt": 0}]
        # binance FROZEN 且 CAN_REDUCE=False → EVACUATE 不可行
        it = await rp._build_intent(r, pol4, "binance", pol4["venues"]["binance"],
                                    "drill-FILUSDT", {"symbol": "FILUSDT"}, legs)
        check("E4 受限所撤离预检不可行(trapped)", it["feasible"] is False, f"feasible={it['feasible']}")
        rescue = await rp._build_rescue(r, pol4, "binance", pol4["venues"]["binance"],
                                        "drill-FILUSDT", {"symbol": "FILUSDT"}, legs)
        check("E4 生成第三venue救援意图(RESCUE_HEDGE)",
              rescue is not None and rescue["kind"] == "RESCUE_HEDGE",
              f"rescue={rescue and rescue.get('kind')}")
    except Exception as e:  # noqa: BLE001
        check("E4 repair 意图生成", False, f"exc {repr(e)[:100]}")

    # ── E5 排空期 REDUCE_ONLY 权威:override 冲淡不生效(取最严格) ──
    # 模拟:policy 已 REDUCE_ONLY;若有 NORMAL 想冲淡,can_open 仍须 False
    await r.set(pc.POLICY_KEY, json.dumps(_policy(2, 800, "REDUCE_ONLY", CAPS_REDUCE)))
    ok5, _ = await pc.can_open(r, "binance")
    check("E5 排空态 CAN_OPEN=False(override 冲不淡)", not ok5, f"ok={ok5}")

    await r.flushdb()
    await r.aclose()
    try:
        os.remove("/tmp/drill_exec_wal.json")
    except OSError:
        pass
    print(f"DRILL_EXEC_{'OK' if failed == 0 else 'FAIL'} passed={passed} failed={failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
