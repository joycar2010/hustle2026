# -*- coding: utf-8 -*-
"""执行安全场景测试床 — V1.1 §18 首版 (2026-07-16)。

锻炼对象 = 本周部署的全部安全机制(真实生产代码, 非平行简化实现):
  S1 watcher预注册: WS早到成交事件不被register覆盖, 终态立即唤醒
  S2 预算护栏: 剩余预算不足一轮监控 → 不下单干净返回
  S3 shield撤单: 监控协程被cancel → 交易所侧撤单仍然发出(防孤儿)
  S4 崩溃补腿: 成交15 XAU → 精确补0.15lot + 记账本 + 幂等(重入不双补)
  S5 严格s-闸: 空clientOrderId拒绝补腿+专项告警+释放幂等位
  S6 未知≠失败: 桥超时不盲目重发(补腿只发1次), 幂等位保留
  S7 核查有限重试: REST失败2次第3次成功 → 补腿完成
  S8 桥HTTP契约: done/partial/reject 四量字段语义(经fake_bridge真HTTP面)
  S9 实际成交消费: 部分成交循环补挂, 总量/均价按桥实际值

用法(testgo/go 服务器): cd /data/hustle2026/backend && venv/bin/python tests/testbed/run_scenarios.py
安全: 全程不触外网/不触真交易所/不写业务表; 仅依赖 quantity_converter 读DB换算系数。
"""
import asyncio
import sys
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def acct(aid="00000000-0000-0000-0000-0000000000aa"):
    return SimpleNamespace(account_id=aid, platform_id=2, api_key="k", api_secret="s", proxy_config=None)


# ── S1 watcher预注册 ─────────────────────────────────────────────────────────
async def s1_watcher_preregistration():
    from app.tasks.broadcast_tasks import notify_order_fill, register_order_watch, \
        unregister_order_watch, _order_fill_registry
    oid = 777001
    notify_order_fill(oid, 15.0, "FILLED", 2400.0)          # WS事件先到
    evt = register_order_watch(oid)                          # 监控后注册
    ok = evt.is_set() and _order_fill_registry.get(oid, {}).get("filled_qty") == 15.0
    unregister_order_watch(oid)
    record("S1 watcher预注册不丢早到成交", ok)


# ── S2 预算护栏 ──────────────────────────────────────────────────────────────
async def s2_budget_guard():
    from app.services.order_executor_v2 import OrderExecutorV2
    ex = OrderExecutorV2()
    ex._precheck_dual_margin_for_open = AsyncMock(return_value={"ok": True, "error": None, "detail": {}})
    place = AsyncMock()
    ex._place_a_side_order = place
    res = await ex.execute_reverse_opening(
        binance_account=acct(), bybit_account=acct("bb"), quantity=15.0,
        binance_price=2400.0, bybit_price=2400.0, spread_threshold=2.0,
        pair_code="XAU", exec_deadline=asyncio.get_event_loop().time() + 1.0)  # 剩1s<一轮所需
    ok = res.get("budget_exhausted") is True and res.get("binance_filled_qty") == 0 \
        and place.await_count == 0
    record("S2 预算不足不下单", ok, f"resp_keys={sorted(k for k in res if res[k])}")


# ── S3 shield撤单 ────────────────────────────────────────────────────────────
async def s3_shield_cancel():
    from app.services.order_executor_v2 import OrderExecutorV2
    ex = OrderExecutorV2()
    cancel = AsyncMock(return_value={"success": True})
    ex.base_executor = SimpleNamespace(cancel_binance_order=cancel,
                                       check_binance_order_status=AsyncMock(return_value={"success": False}))
    task = asyncio.create_task(ex._monitor_binance_order(acct(), "XAUUSDT", 777002, timeout=30.0))
    await asyncio.sleep(0.5)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    ok = cancelled and cancel.await_count == 1
    record("S3 监控被杀shield撤单仍发出", ok, f"cancel_calls={cancel.await_count}")


def _repair_ex(check=None, place=None):
    return SimpleNamespace(
        pair_code="XAU", strategy_id="testbed", user_id="testbed",
        position_mgr=SimpleNamespace(record_opening=Mock()),
        order_executor=SimpleNamespace(base_executor=SimpleNamespace(
            check_binance_order_status=check or AsyncMock(return_value={"success": True, "filled_qty": 15.0}),
            place_bybit_order=place or AsyncMock(return_value={"success": True, "order_id": "99"}))),
        _send_single_leg_alert=AsyncMock())


def _ctx(oid, coid="s-test-1"):
    return {"order_id": oid, "repair_armed": True, "client_order_id": coid,
            "hedged_xau": 0.0, "symbol": "XAUUSDT", "sym_b": "XAUUSD+",
            "hedge_is_buy": True, "hedge_close_position": False, "hedge_multiplier": 1.0}


# ── S4 崩溃补腿 成功+幂等 ────────────────────────────────────────────────────
async def s4_crash_repair():
    from app.services.continuous_executor import _crash_repair_leg
    ex = _repair_ex()
    ctx = _ctx(424101)
    await _crash_repair_leg(ex, ctx, 0, "reverse_opening", acct(), acct("bb"))
    p = ex.order_executor.base_executor.place_bybit_order
    call_kw = p.await_args.kwargs if p.await_args else {}
    lot_ok = call_kw.get("quantity") == "0.15" and call_kw.get("side") == "Buy" \
        and call_kw.get("close_position") is False
    ledger_ok = ex.position_mgr.record_opening.call_count == 1
    await _crash_repair_leg(ex, ctx, 0, "reverse_opening", acct(), acct("bb"))  # 重入
    idem_ok = p.await_count == 1
    record("S4 补腿精确量+记账+幂等", lot_ok and ledger_ok and idem_ok,
           f"lot={call_kw.get('quantity')} ledger={ledger_ok} repeat_calls={p.await_count}")


# ── S5 严格s-闸 ──────────────────────────────────────────────────────────────
async def s5_strict_identity():
    from app.services.continuous_executor import _crash_repair_leg, _REPAIRED_ORDERS
    ex = _repair_ex()
    oid = 424102
    await _crash_repair_leg(ex, _ctx(oid, coid=""), 0, "reverse_opening", acct(), acct("bb"))
    p = ex.order_executor.base_executor.place_bybit_order
    alert_kw = ex._send_single_leg_alert.await_args.kwargs if ex._send_single_leg_alert.await_args else {}
    trig = (alert_kw.get("exec_result") or {}).get("single_leg_details", {}).get("trigger", "")
    ok = p.await_count == 0 and trig == "AUTO_REPAIR_IDENTITY_REFUSED" and oid not in _REPAIRED_ORDERS
    record("S5 空clientOrderId拒补+告警+释放幂等位", ok, f"trigger={trig}")


# ── S6 未知≠失败 不盲发 ──────────────────────────────────────────────────────
async def s6_unknown_no_resend():
    from app.services.continuous_executor import _crash_repair_leg, _REPAIRED_ORDERS
    place = AsyncMock(side_effect=asyncio.TimeoutError())
    ex = _repair_ex(place=place)
    oid = 424103
    await _crash_repair_leg(ex, _ctx(oid), 0, "reverse_opening", acct(), acct("bb"))
    ok = place.await_count == 1 and oid in _REPAIRED_ORDERS
    record("S6 桥超时UNKNOWN只发1次+幂等位保留", ok, f"place_calls={place.await_count}")


# ── S7 核查有限重试 ──────────────────────────────────────────────────────────
async def s7_check_retry():
    from app.services.continuous_executor import _crash_repair_leg
    check = AsyncMock(side_effect=[Exception("net1"), Exception("net2"),
                                   {"success": True, "filled_qty": 15.0}])
    ex = _repair_ex(check=check)
    await _crash_repair_leg(ex, _ctx(424104), 0, "reverse_opening", acct(), acct("bb"))
    p = ex.order_executor.base_executor.place_bybit_order
    ok = check.await_count == 3 and p.await_count == 1
    record("S7 REST核查重试3次后补腿成功", ok, f"check={check.await_count} place={p.await_count}")


# ── S8 桥HTTP契约 ────────────────────────────────────────────────────────────
async def s8_bridge_contract():
    import httpx
    from tests.testbed.fake_bridge import app as bridge_app
    transport = httpx.ASGITransport(app=bridge_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as c:
        await c.post("/ctl/behavior", json={"mode": "done"})
        r1 = (await c.post("/mt5/order", json={"symbol": "XAUUSD+", "volume": 0.15, "order_type": "BUY"})).json()
        await c.post("/ctl/behavior", json={"mode": "partial", "filled_ratio": 0.6})
        r2 = (await c.post("/mt5/order", json={"symbol": "XAUUSD+", "volume": 0.15, "order_type": "BUY"})).json()
        await c.post("/ctl/behavior", json={"mode": "reject"})
        r3 = await c.post("/mt5/order", json={"symbol": "XAUUSD+", "volume": 0.15, "order_type": "BUY"})
    ok = (r1["filled_volume"] == r1["normalized_volume"] == 0.15 and r1["partial"] is False
          and r2["partial"] is True and abs(r2["filled_volume"] - 0.09) < 1e-9
          and abs(r2["remaining_volume"] - 0.06) < 1e-9 and r2["retcode"] == 10010
          and r3.status_code == 400)
    record("S8 桥契约done/partial/reject四量字段", ok,
           f"partial: filled={r2['filled_volume']} remaining={r2['remaining_volume']}")


# ── S9 实际成交消费: 部分成交循环补挂 ────────────────────────────────────────
async def s9_actual_fill_consumption():
    from app.services.order_executor_v2 import OrderExecutorV2
    ex = OrderExecutorV2()
    ex.bybit_timeout = 0.05
    ex._mt5_actual_fill_enabled = lambda account: True
    place = AsyncMock(side_effect=[
        {"success": True, "order_id": "1", "data": {"filled_volume": 0.10, "price": 2400.0, "partial": True}},
        {"success": True, "order_id": "2", "data": {"filled_volume": 0.05, "price": 2401.0, "partial": False}},
    ])
    ex.base_executor = SimpleNamespace(place_bybit_order=place)
    res = await ex._execute_bybit_market_buy(acct(), "XAUUSD+", 0.15, close_position=False)
    fq, ap = res.get("filled_qty"), res.get("avg_price", 0)
    exp_avg = (0.10 * 2400.0 + 0.05 * 2401.0) / 0.15
    ok = abs(fq - 0.15) < 1e-9 and abs(ap - exp_avg) < 0.01 and place.await_count == 2
    record("S9 部分成交循环补挂+真实均价", ok, f"filled={fq} avg={ap:.2f} calls={place.await_count}")


async def main():
    scenarios = [s1_watcher_preregistration, s2_budget_guard, s3_shield_cancel,
                 s4_crash_repair, s5_strict_identity, s6_unknown_no_resend,
                 s7_check_retry, s8_bridge_contract, s9_actual_fill_consumption]
    for s in scenarios:
        try:
            await s()
        except Exception as e:
            record(s.__name__, False, f"EXCEPTION: {e!r}")
    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== 测试床结果: {n_ok}/{len(RESULTS)} PASS =====")
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    import logging
    logging.disable(logging.WARNING)  # 压掉生产代码的错误日志噪音(场景故意制造失败)
    sys.exit(asyncio.run(main()))
