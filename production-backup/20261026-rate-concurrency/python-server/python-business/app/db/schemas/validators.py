"""规则字段级校验工具 —— 防呆:非法值在入库前直接 422 拒掉,不再静默写进实盘引擎。

设计原则:
- 仅校验「已提供」的值(None 直接放行,保留 Optional 的"不改"语义)。
- 边界从宽到合理即可,目标是挡住手滑/错位(多打一个零、负点差、配速超硬顶、分层不等于100),
  不是精确业务约束。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def rng(v, lo, hi, name: str):
    """数值区间校验 [lo, hi];None 放行。"""
    if v is None:
        return v
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} 不是合法数值: {v!r}")
    if d < Decimal(str(lo)) or d > Decimal(str(hi)):
        raise ValueError(f"{name} 应在 {lo}~{hi} 之间(当前 {v})")
    return v


def follow_type(v):
    if v is None or v == "":
        return v
    if str(v) not in ("market", "limit"):
        raise ValueError("跟单方式只能是 market 或 limit")
    return v


def tier_ratios(v):
    """分层建仓 "偏移%:数量%,..." 校验:各档数量% 之和必须为 100;空串放行(=不分层)。"""
    if v is None or str(v).strip() == "":
        return v
    total = Decimal("0")
    for part in str(v).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError("分层建仓格式应为 偏移%:数量%,如 0.5:30,0.8:30,1.2:40")
        off, pct = part.split(":", 1)
        try:
            Decimal(off.strip())
            p = Decimal(pct.strip())
        except (InvalidOperation, ValueError):
            raise ValueError(f"分层建仓数值非法: {part}")
        if p < 0:
            raise ValueError(f"分层建仓数量% 不能为负: {part}")
        total += p
    if total != Decimal("100"):
        raise ValueError(f"分层建仓各档数量% 之和应为 100(当前 {total})")
    return v


def transfer_order(v):
    if v is None or v == "":
        return v
    parts = [p.strip() for p in str(v).split(",")]
    if sorted(parts) != ["futures", "margin", "spot"]:
        raise ValueError("划转顺序必须是 spot/futures/margin 三者的排列")
    return v
