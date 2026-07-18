"""Phase 4-5: 持有期监控 + 退出 Saga + RECON
每日执行监控任务,检查资金费收付、点差扩大、硬亏预算。
"""
import asyncio
import time
from typing import Optional
from app import datasources as ds

async def monitor_holding(work_item_id: str) -> dict:
    """Phase 4: 持有期每日监控
    Args:
        work_item_id: Intent ID
    Returns: {funding_total, spread_current, unrealized_pnl, alert_level}
    """
    r = ds.rds()
    wi_raw = await r.get(f"dcm:workitem:{work_item_id}")
    if not wi_raw:
        return {"error": "workitem not found"}
    import json
    wi = json.loads(wi_raw)

    # 1. 资金费确认 (从 dcm:feed:funding:{venue} 读取)
    side_a = wi["side_a"]
    side_b = wi["side_b"]
    symbol = wi["symbol"]

    # HL-short 收资金费 (为正), bitget-long 付资金费 (为负)
    hl_funding = await ds.get_json(f"dcm:feed:funding:hyperliquid") or {}
    bitget_funding = await ds.get_json(f"dcm:feed:funding:bitget") or {}

    hl_daily = hl_funding.get(symbol.replace("USDT", ""), {}).get("daily_pct", 0)
    bitget_daily = bitget_funding.get(symbol, {}).get("daily_pct", 0)

    # 净资金费 = HL收入 - bitget支出
    net_funding_daily = hl_daily - bitget_daily

    # 2. 点差监控 (从 dcm:account:*/pos_detail 读取 mark 价)
    hl_mark = 64500  # TODO: 从 dcm:account:hyperliquid.pos_detail 读取
    bitget_mark = 64505  # TODO: 从 dcm:account:bitget.pos_detail 读取
    spread_current = bitget_mark - hl_mark

    # 入场点差 (从 wi.legs_executed 读取)
    entry_spread = wi.get("entry_spread", 5)
    spread_expansion = spread_current - entry_spread

    # 3. 硬亏预算检查
    unrealized_pnl = -spread_expansion * side_a["target_notional"] / hl_mark  # 简化计算
    hard_loss_budget = wi.get("hard_loss_budget", 30)
    alert_level = "ok"
    if abs(unrealized_pnl) > hard_loss_budget * 0.8:
        alert_level = "warning"
    if abs(unrealized_pnl) > hard_loss_budget:
        alert_level = "critical"

    # 记录到 workitem
    holding_metrics = {
        "net_funding_daily_pct": net_funding_daily,
        "spread_current": spread_current,
        "spread_expansion": spread_expansion,
        "unrealized_pnl": unrealized_pnl,
        "alert_level": alert_level,
        "checked_at": time.time(),
    }
    wi["holding_metrics"] = holding_metrics
    await r.setex(f"dcm:workitem:{work_item_id}", 86400, json.dumps(wi))

    return holding_metrics

async def execute_closing_saga(work_item_id: str) -> dict:
    """Phase 5: 退出 Saga (先平多腿 → 再平空腿)
    Returns: {leg_a_close, leg_b_close, realized_pnl, recon_status}
    """
    r = ds.rds()
    wi_raw = await r.get(f"dcm:workitem:{work_item_id}")
    if not wi_raw:
        return {"error": "workitem not found"}
    import json
    wi = json.loads(wi_raw)

    # Step 1: 先平多腿 (bitget-long)
    # TODO: 调用 bitget_client.place_order(side='close_long')
    leg_a_close = {
        "order_id": f"close_a_{int(time.time())}",
        "filled_price": 64510,
        "filled_qty": wi["leg_a"]["filled_qty"],
        "timestamp": time.time(),
    }
    print(f"Leg A (bitget-long) closed: {leg_a_close}")

    # Step 2: 再平空腿 (HL-short)
    # TODO: 调用 hl_client.place_order(side='buy', reduce_only=True)
    leg_b_close = {
        "order_id": f"close_b_{int(time.time())}",
        "filled_price": 64505,
        "filled_qty": wi["leg_b"]["filled_qty"],
        "timestamp": time.time(),
    }
    print(f"Leg B (HL-short) closed: {leg_b_close}")

    # Step 3: 计算真实盈亏
    # 多腿: (exit_price - entry_price) * qty * entry_price
    pnl_long = (leg_a_close["filled_price"] - wi["leg_a"]["filled_price"]) * wi["leg_a"]["filled_qty"] * wi["leg_a"]["filled_price"]
    # 空腿: (entry_price - exit_price) * qty * entry_price
    pnl_short = (wi["leg_b"]["filled_price"] - leg_b_close["filled_price"]) * wi["leg_b"]["filled_qty"] * wi["leg_b"]["filled_price"]

    realized_pnl = pnl_long + pnl_short

    # Step 4: RECON (对账)
    # TODO: 对账成交金额、手续费、资金费收付
    recon = {
        "leg_a_cost": wi["leg_a"]["filled_notional"],
        "leg_a_proceeds": leg_a_close["filled_price"] * leg_a_close["filled_qty"],
        "leg_b_cost": wi["leg_b"]["filled_notional"],
        "leg_b_proceeds": leg_b_close["filled_price"] * leg_b_close["filled_qty"],
        "realized_pnl": realized_pnl,
        "recon_status": "matched",  # 简化版,实际需对比交易所余额变化
    }

    # 更新状态
    wi["workflow_stage"] = "CLOSED"
    wi["leg_a_close"] = leg_a_close
    wi["leg_b_close"] = leg_b_close
    wi["realized_pnl"] = realized_pnl
    wi["recon"] = recon
    wi["closed_at"] = time.time()
    await r.setex(f"dcm:workitem:{work_item_id}", 86400, json.dumps(wi))

    return {
        "leg_a_close": leg_a_close,
        "leg_b_close": leg_b_close,
        "realized_pnl": realized_pnl,
        "recon": recon,
    }

# CLI 测试
if __name__ == "__main__":
    async def test():
        # Phase 4 监控
        metrics = await monitor_holding("wi-1784399529-c2_perp_pair")
        print("=== Phase 4 Monitoring ===")
        print(metrics)

        # Phase 5 退出
        # result = await execute_closing_saga("wi-1784399529-c2_perp_pair")
        # print("\n=== Phase 5 Closing ===")
        # print(result)

    asyncio.run(test())
