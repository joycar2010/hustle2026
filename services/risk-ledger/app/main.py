"""risk-ledger v1(骨架):跨域风控面,独立第三方进程(C 机,与执行面分机)。

v1 监察范围(30s 一轮):
  R1 服务心跳巡检:EXPECTED 服务的 dcm:hb:* 缺失/停更 → 告警
  R2 coin 引擎活性:dcm:engine:coin:state 中 RUNNING scope 的 last_heartbeat 停走 → 告警
  R3 coin 僵尸仓:非终态仓位(PENDING_BORROW/BORROWED_IDLE/PENDING_REPAY)超龄 → 告警
     (PENDING_BORROW 钉死币旧伤的独立第三方哨兵)
  R4 feed 吞吐:updates_30s==0 → 告警
  净敞口 v1=意图口径汇总(coin 意图账逐币 net_base,只报不判),写 dcm:risk:status 供 gateway 展示。

实盘对账(五所只读 API=最终真相源)接口留位:API key 未配置前如实报 unconfigured,不猜。

铁律(coin 事故史):风控面**只告警不动手**——绝不自愈、绝不改仓、绝不写任何业务键;
独立于一切执行进程存活;告警走共享节流(dcm:throttle:),致命级绕过节流。
"""
import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import FeishuTarget, Notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("risk-ledger")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_RISK_INTERVAL_SEC", "30"))
STALE_POS_SEC = int(os.environ.get("DCM_RISK_STALE_POS_SEC", "1800"))
THROTTLE_SEC = int(os.environ.get("DCM_RISK_THROTTLE_SEC", "1800"))

# 期望在场的服务及其心跳最大年龄(秒)。缺失键==停更同罪。
EXPECTED_HB = {
    "feed-cex": 120,
    "coin-bridge": 240,
    "universe-sync": 7500,
    "gateway": 120,
    "decision": 120,
    "engine-dualperp": 120,
}
STALE_STATUSES = ("PENDING_BORROW", "BORROWED_IDLE", "PENDING_REPAY")

notifier = Notifier(
    REDIS_URL, "risk-ledger",
    feishu=FeishuTarget(webhook_url=os.environ.get("DCM_FEISHU_WEBHOOK", "")),
    throttle_interval_sec=THROTTLE_SEC, throttle_max_count=1,
)


async def fire(key: str, title: str, content: str, level: str = "warn"):
    """告警=日志+飞书(若配置)+跑马灯发布,经共享节流;绝不抛异常打断巡检轮。"""
    try:
        res = await asyncio.to_thread(notifier.fire, key, title, content,
                                      level=level, marquee=True, color="#ef4444")
        log.warning("ALERT[%s] %s | %s -> %s", key, title, content, res)
    except Exception as e:
        log.error("alert fire failed %s: %r", key, e)


async def get_json(r: aioredis.Redis, key: str):
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        log.warning("redis get %s failed: %r", key, e)
        return None


def intent_net(positions: list) -> dict:
    """coin 意图账逐币净 delta(base 口径,粗):现货腿=买回-卖出,合约腿=多头数量。
    只汇总呈现,不在 v1 下判断——实盘核对上线后才谈差异告警。"""
    net: dict[str, float] = {}
    for p in positions:
        try:
            sym = p.get("symbol") or "?"
            spot = float(p.get("spot_buy_qty") or 0) - float(p.get("spot_sell_qty") or 0)
            fut = float(p.get("futures_long_qty") or 0)
            net[sym] = round(net.get(sym, 0.0) + spot + fut, 8)
        except (TypeError, ValueError):
            continue
    return net


async def check_round(r: aioredis.Redis) -> dict:
    now = int(time.time())
    status: dict = {"ts": now, "services": {}, "coin": {}, "reconcile": {"configured": False}}
    alerts = 0

    # R1 服务心跳巡检
    for svc, max_age in EXPECTED_HB.items():
        hb = await get_json(r, f"dcm:hb:{svc}")
        if hb is None:
            status["services"][svc] = "missing"
            await fire(f"hb-missing:{svc}", f"{svc} 心跳缺失", f"dcm:hb:{svc} 键不存在(服务死亡或总线不可达)")
            alerts += 1
            continue
        age = now - int(hb.get("ts") or 0)
        if age > max_age:
            status["services"][svc] = f"stale({age}s)"
            await fire(f"hb-stale:{svc}", f"{svc} 心跳停更", f"最后心跳 {age}s 前(阈值 {max_age}s)")
            alerts += 1
        else:
            status["services"][svc] = "ok"
        # R4 feed 吞吐归零
        if svc == "feed-cex" and status["services"][svc] == "ok" and int(hb.get("updates") or 0) == 0:
            await fire("feed-zero", "feed-cex 吞吐归零", "30s 窗口 updates=0(全所静默,疑总线/上游断)")
            alerts += 1

    # R2 coin 引擎活性(桥透传的 engine_state;桥自身死活已在 R1)
    state = await get_json(r, "dcm:engine:coin:state")
    if state:
        scopes = state.get("engine_state") or []
        stale_scopes = []
        for s in scopes:
            if s.get("status") == "RUNNING":
                hb_ts = int(s.get("heartbeat_ts") or 0)
                if hb_ts and now - hb_ts > 120:
                    # 带 user_id/pid 消歧义:engine_state 可能存在同名 scope 多行
                    # (真引擎行心跳鲜活 + 卡 RUNNING 的僵尸行并存,testgo C层僵尸假运行的 coin 版)
                    stale_scopes.append(
                        f"{s.get('scope')}/u{s.get('user_id')}/pid{s.get('pid')}({(now - hb_ts) // 60}min)")
        status["coin"]["engine_scopes"] = len(scopes)
        status["coin"]["stale_scopes"] = stale_scopes
        if stale_scopes:
            await fire("coin-engine-stale", "coin 引擎心跳停走",
                       f"RUNNING scope 停走: {', '.join(stale_scopes)}", level="fatal")
            alerts += 1

    # R3 coin 僵尸仓 + 净敞口(意图口径)
    snap = await get_json(r, "dcm:engine:coin:positions")
    if snap:
        positions = snap.get("positions") or []
        status["coin"]["open_positions"] = len(positions)
        stale_pos = []
        for p in positions:
            st = p.get("status")
            upd = int(p.get("updated_ts") or 0)
            if st in STALE_STATUSES and upd and now - upd > STALE_POS_SEC:
                stale_pos.append({"symbol": p.get("symbol"), "status": st,
                                  "age_min": (now - upd) // 60,
                                  "borrow_qty": p.get("borrow_qty")})
        status["coin"]["stale_positions"] = stale_pos
        status["coin"]["intent_net"] = intent_net(positions)
        for sp in stale_pos:
            await fire(f"stalepos:{sp['symbol']}", f"coin 非终态仓位滞留 {sp['symbol']}",
                       f"status={sp['status']} 已滞留 {sp['age_min']}min borrow_qty={sp['borrow_qty']}"
                       f" — 僵尸仓/钉死币前兆,需人工核")
            alerts += 1

    status["alerts_this_round"] = alerts
    return status


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    hb = Heartbeat(REDIS_URL, "risk-ledger", interval_sec=INTERVAL, ttl_sec=INTERVAL * 3 + 30)
    log.info("risk-ledger up interval=%ss stale_pos=%ss expected=%s",
             INTERVAL, STALE_POS_SEC, list(EXPECTED_HB))
    while True:
        try:
            status = await check_round(r)
            hb.extra = {"alerts": status.get("alerts_this_round", 0)}
            await r.set("dcm:risk:status", json.dumps(status, ensure_ascii=False, default=str), ex=180)
            await hb.beat_once()
            log.info("LEDGER_OK services=%s alerts=%d",
                     status.get("services"), status.get("alerts_this_round", 0))
        except Exception:
            log.exception("check round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
