"""InvestorProjection 幂等重建 (M6 §5)
目标:基于 share_account + nav_snapshot 幂等计算 Units/权益/份额比例,供客户门户/对账单使用。
铁律:①幂等=同一 snapshot 多次计算结果不变;②不可篡改 share_account.total_units;③客户只读投影。
"""
import asyncio
from decimal import Decimal
from app import datasources as ds

async def rebuild_investor_projection(snapshot_id: str = None) -> dict:
    """重建 InvestorProjection:基于最新或指定 NAV 快照 + share_account 计算份额投影。
    返回:{investor_id: {units, equity_usdt, share_pct, nav_per_unit}}"""
    pool = await ds.pg()
    if not pool:
        return {}
    # 1. 获取 NAV 快照
    if snapshot_id:
        snap = await pool.fetchrow("SELECT * FROM nav_snapshot WHERE snapshot_id=$1", snapshot_id)
    else:
        snap = await pool.fetchrow(
            "SELECT * FROM nav_snapshot WHERE snapshot_type='FINALIZED' ORDER BY as_of DESC LIMIT 1")
    if not snap:
        return {}
    nav_per_unit = Decimal(str(snap["nav_per_unit"]))
    total_units = Decimal(str(snap["total_units"]))
    # 2. 获取所有 share_account
    accounts = await pool.fetch(
        "SELECT investor_id, account_name, account_type, total_units FROM share_account WHERE status='active'")
    projection = {}
    for acct in accounts:
        units = Decimal(str(acct["total_units"]))
        equity = units * nav_per_unit
        share_pct = (units / total_units * 100) if total_units > 0 else Decimal(0)
        projection[acct["investor_id"]] = {
            "investor_id": acct["investor_id"],
            "account_name": acct["account_name"],
            "account_type": acct["account_type"],
            "units": float(units),
            "equity_usdt": float(equity),
            "share_pct": float(share_pct),
            "nav_per_unit": float(nav_per_unit),
            "snapshot_id": snap["snapshot_id"],
            "as_of": snap["as_of"].isoformat() if snap["as_of"] else None,
        }
    return projection

async def get_investor_summary(investor_id: int) -> dict:
    """获取单个投资人摘要(供客户门户使用)。"""
    proj = await rebuild_investor_projection()
    return proj.get(investor_id, {})

# CLI 测试
if __name__ == "__main__":
    async def main():
        proj = await rebuild_investor_projection()
        print("=== InvestorProjection 幂等重建 ===")
        for inv_id, p in proj.items():
            print(f"{p['account_name']:12s} Units:{p['units']:>10.2f} Eq:{p['equity_usdt']:>8.2f}U Share:{p['share_pct']:>6.2f}%")
        print(f"\nTotal accounts: {len(proj)}")
    asyncio.run(main())
