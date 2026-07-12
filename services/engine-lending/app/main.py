"""dcm-engine-lending —— S4 借贷利率套利 shadow 版执行器（只记账不动钱）。

定位：lending-advisor 已产出三率净差榜(dcm:lending:ranking)，本服务把"榜"变"决策流水"：
  would_enter / hold / would_exit 逐轮落 lending_shadow_log，攒 E 分布与换手率，
  为 armed 版（币安借币→卖出→申购理财/收资金费）提供 shadow 战绩对照。
纪律（dualperp/basis 同款）：
  - shadow 永不下单；armed 另行专场 + 用户显式放行
  - 退出滞回：连续 EXIT_STRIKES 轮不达标才 would_exit（advisor 退出滞回课）
  - 数据超龄(>1800s)绝不给决策——ranking 停更时全体 hold 并如实标注
键契约：
  dcm:engine:lending:positions  {ts, mode:"shadow", would_hold:[{coin,...}], slots}
  dcm:hb:engine-lending         心跳(EX 240)
"""
import asyncio
import json
import logging
import os
import time

import asyncpg
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("engine-lending")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_LEND_INTERVAL_SEC", "300"))
ENTER_PCT = float(os.environ.get("DCM_LEND_ENTER_PCT", "1.0"))    # 入场净差 %/d
EXIT_PCT = float(os.environ.get("DCM_LEND_EXIT_PCT", "0.4"))     # 退出净差 %/d
TARGET_USDT = float(os.environ.get("DCM_LEND_TARGET_USDT", "50"))
MAX_SLOTS = int(os.environ.get("DCM_LEND_MAX_SLOTS", "5"))
EXIT_STRIKES = int(os.environ.get("DCM_LEND_EXIT_STRIKES", "3"))
RANK_STALE_SEC = int(os.environ.get("DCM_LEND_RANK_STALE_SEC", "1800"))

SNAP_KEY = "dcm:engine:lending:positions"
HB_KEY = "dcm:hb:engine-lending"


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2) if PG_DSN else None
    log.info("engine-lending up mode=shadow interval=%ss enter=%s%%/d exit=%s%%/d slots=%s",
             INTERVAL, ENTER_PCT, EXIT_PCT, MAX_SLOTS)

    # 重启恢复：现读自己的快照认领 would_hold（回放旧快照课：只认领 coin 名单，指标全部现算）
    held: dict[str, dict] = {}
    strikes: dict[str, int] = {}
    try:
        old = json.loads(await r.get(SNAP_KEY) or "null")
        if old and old.get("would_hold"):
            held = {h["coin"]: {"since": h.get("since", int(time.time()))} for h in old["would_hold"]}
            log.info("resume would_hold=%s", sorted(held))
    except Exception as e:  # noqa: BLE001
        log.warning("resume failed: %r", e)

    while True:
        try:
            await _round(r, pool, held, strikes)
        except Exception as e:  # noqa: BLE001
            log.warning("round failed: %r", e)
        await asyncio.sleep(INTERVAL)


async def _log_row(pool, coin, rk, decision, note=""):
    if pool is None:
        return
    try:
        await pool.execute(
            "INSERT INTO lending_shadow_log(coin,net_daily_pct,funding_abs,earn_pct,borrow_pct,"
            "decision,target_usdt,note) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            coin, rk.get("net_daily_pct"), rk.get("funding_abs"), rk.get("earn"),
            rk.get("borrow"), decision, TARGET_USDT, note)
    except Exception as e:  # noqa: BLE001
        log.warning("shadow log write failed: %r", e)


async def _round(r, pool, held: dict, strikes: dict):
    now = int(time.time())
    raw = await r.get("dcm:lending:ranking")
    ranking = json.loads(raw) if raw else None
    fresh = bool(ranking and now - int(ranking.get("ts") or 0) < RANK_STALE_SEC)
    by_coin = {x["coin"]: x for x in (ranking.get("top") or [])} if ranking else {}

    entered, exited = [], []
    if not fresh:
        # 数据超龄：不进不出，如实标注（绝不拿旧榜做决策）
        note = f"ranking 超龄({now - int((ranking or {}).get('ts') or 0)}s)，全体 hold"
        log.warning(note)
    else:
        # 退出（滞回）：不达标或掉榜 → 记 strike，连续 EXIT_STRIKES 轮才 would_exit
        for coin in list(held):
            rk = by_coin.get(coin)
            ok = rk is not None and float(rk.get("net_daily_pct") or 0) >= EXIT_PCT
            if ok:
                strikes.pop(coin, None)
                continue
            strikes[coin] = strikes.get(coin, 0) + 1
            if strikes[coin] >= EXIT_STRIKES:
                await _log_row(pool, coin, rk or {}, "would_exit",
                               f"净差不达标/掉榜 连续{strikes[coin]}轮")
                held.pop(coin, None)
                strikes.pop(coin, None)
                exited.append(coin)
        # 入场：榜上净差≥ENTER 且有空位
        for x in (ranking.get("top") or []):
            coin = x["coin"]
            if coin in held or len(held) >= MAX_SLOTS:
                continue
            if float(x.get("net_daily_pct") or 0) >= ENTER_PCT:
                held[coin] = {"since": now}
                await _log_row(pool, coin, x, "would_enter",
                               f"净差 {x.get('net_daily_pct')}%/d ≥ {ENTER_PCT}")
                entered.append(coin)
        # 在管 hold 流水（低频：每轮一行，供净差走势/E 分布分析）
        for coin in held:
            rk = by_coin.get(coin)
            if rk:
                await _log_row(pool, coin, rk, "hold")

    snap = {"ts": now, "mode": "shadow", "slots": f"{len(held)}/{MAX_SLOTS}",
            "target_usdt": TARGET_USDT,
            "would_hold": [{"coin": c, "since": v["since"],
                            "net_daily_pct": (by_coin.get(c) or {}).get("net_daily_pct")}
                           for c, v in sorted(held.items())],
            "ranking_fresh": fresh}
    await r.set(SNAP_KEY, json.dumps(snap, ensure_ascii=False), ex=900)
    await r.set(HB_KEY, json.dumps({"service": "engine-lending", "ts": now,
                                    "pid": os.getpid(), "held": len(held),
                                    "entered": len(entered), "exited": len(exited)}), ex=240)
    log.info("ROUND_OK held=%s entered=%s exited=%s fresh=%s",
             sorted(held), entered, exited, fresh)


if __name__ == "__main__":
    asyncio.run(main())
