"""手工记账/对账(test站 frontend-www)。

口径: 每主账户(user)一条链: 首笔=总金额预设值(baseline, daily_pnl=0),
之后每天录一笔当日总金额, daily_pnl = 本笔 - 上一笔(录入时落库)。
- 同日重复录入 = 覆盖当天(UPSERT), 之后全链重算(条数少, 全链重算最稳)。
- 严格按登录 user 隔离; 子账户 403(不走 user_pnl_links 合并, 私账语义)。
- 对账差值: sys_pnl = 同北京日的系统日收益(直接读 binance_income + mt5_deals
  持久化表, 与收益页 income_deals_based 同口径, 零交易所请求), diff = 手工 - 系统。
"""
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.api.v1.subaccount import ViewContext, get_view_context

logger = logging.getLogger(__name__)
router = APIRouter()


class EntryIn(BaseModel):
    entry_date: date
    total_amount: Decimal = Field(..., ge=0)
    note: Optional[str] = Field(None, max_length=200)


def _deny_sub(ctx: ViewContext):
    if ctx.is_sub:
        raise HTTPException(status_code=403, detail="子账户无手工记账功能")


async def _recompute_chain(db, user_id: str):
    """全链重算: 按 entry_date 升序, 首笔 baseline(daily_pnl=0), 其余=本笔-上一笔。"""
    await db.execute(text("""
        WITH ordered AS (
            SELECT id,
                   total_amount,
                   LAG(total_amount) OVER (ORDER BY entry_date) AS prev_amount,
                   ROW_NUMBER() OVER (ORDER BY entry_date) AS rn
            FROM manual_ledger WHERE user_id = CAST(:u AS UUID)
        )
        UPDATE manual_ledger m SET
            daily_pnl  = CASE WHEN o.rn = 1 THEN 0 ELSE o.total_amount - o.prev_amount END,
            is_baseline = (o.rn = 1),
            updated_at = now()
        FROM ordered o WHERE m.id = o.id
    """), {"u": str(user_id)})


async def _sys_pnl_by_bjdate(db, user_id: str, dates: list) -> dict:
    """系统日收益(北京日): binance income(非TRANSFER) + mt5平仓(entry=1,symbol非空)。"""
    if not dates:
        return {}
    rows = (await db.execute(text("""
        WITH aids AS (SELECT account_id FROM accounts WHERE user_id = CAST(:u AS UUID)),
        b AS (
            SELECT (to_timestamp(income_time_ms/1000) + interval '8 hours')::date d, sum(income) v
            FROM binance_income WHERE account_id IN (SELECT account_id FROM aids)
              AND income_type <> 'TRANSFER'
            GROUP BY 1),
        m AS (
            SELECT (deal_time_utc + interval '8 hours')::date d, sum(profit+swap+commission) v
            FROM mt5_deals WHERE account_id IN (SELECT account_id FROM aids)
              AND entry = 1 AND symbol <> ''
            GROUP BY 1)
        SELECT COALESCE(b.d, m.d) d, COALESCE(b.v,0) + COALESCE(m.v,0) v
        FROM b FULL OUTER JOIN m ON b.d = m.d
        WHERE COALESCE(b.d, m.d) = ANY(CAST(:ds AS date[]))
    """), {"u": str(user_id), "ds": dates})).all()
    return {r[0].isoformat(): float(r[1]) for r in rows}


@router.get("/entries")
async def list_entries(
    month: Optional[str] = Query(None, description="YYYY-MM, 缺省=全部"),
    ctx: ViewContext = Depends(get_view_context),
):
    _deny_sub(ctx)
    uid = str(ctx.auth_user_id)
    async with AsyncSessionLocal() as db:
        cond = "AND to_char(entry_date,'YYYY-MM') = :m" if month else ""
        params = {"u": uid}
        if month:
            params["m"] = month
        rows = (await db.execute(text(f"""
            SELECT entry_date, total_amount, daily_pnl, is_baseline, note, updated_at
            FROM manual_ledger WHERE user_id = CAST(:u AS UUID) {cond}
            ORDER BY entry_date DESC
        """), params)).all()
        dates = [r[0] for r in rows]
        sys_map = await _sys_pnl_by_bjdate(db, uid, dates)
        s = (await db.execute(text("""
            SELECT
              (SELECT total_amount FROM manual_ledger WHERE user_id=CAST(:u AS UUID) ORDER BY entry_date ASC LIMIT 1),
              (SELECT total_amount FROM manual_ledger WHERE user_id=CAST(:u AS UUID) ORDER BY entry_date DESC LIMIT 1),
              (SELECT entry_date FROM manual_ledger WHERE user_id=CAST(:u AS UUID) ORDER BY entry_date ASC LIMIT 1),
              (SELECT count(*) FROM manual_ledger WHERE user_id=CAST(:u AS UUID))
        """), {"u": uid})).first()
    entries = []
    for r in rows:
        dk = r[0].isoformat()
        sysv = sys_map.get(dk)
        manual = float(r[2])
        entries.append({
            "entry_date": dk, "total_amount": float(r[1]), "daily_pnl": manual,
            "is_baseline": bool(r[3]), "note": r[4],
            "sys_pnl": (round(sysv, 2) if sysv is not None else None),
            "diff": (round(manual - sysv, 2) if (sysv is not None and not r[3]) else None),
            "updated_at": r[5].isoformat() if r[5] else None,
        })
    baseline = float(s[0]) if s and s[0] is not None else None
    latest = float(s[1]) if s and s[1] is not None else None
    return {
        "entries": entries,
        "summary": {
            "baseline": baseline,
            "baseline_date": s[2].isoformat() if s and s[2] else None,
            "latest": latest,
            "cumulative_pnl": (round(latest - baseline, 2) if baseline is not None and latest is not None else None),
            "entry_count": int(s[3]) if s else 0,
        },
    }


@router.post("/entries")
async def upsert_entry(body: EntryIn, ctx: ViewContext = Depends(get_view_context)):
    _deny_sub(ctx)
    uid = str(ctx.auth_user_id)
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO manual_ledger(user_id, entry_date, total_amount, note)
            VALUES (CAST(:u AS UUID), :d, :amt, :note)
            ON CONFLICT (user_id, entry_date) DO UPDATE SET
                total_amount = EXCLUDED.total_amount,
                note = COALESCE(EXCLUDED.note, manual_ledger.note),
                updated_at = now()
        """), {"u": uid, "d": body.entry_date, "amt": body.total_amount, "note": body.note})
        await _recompute_chain(db, uid)
        await db.commit()
        r = (await db.execute(text("""
            SELECT daily_pnl, is_baseline FROM manual_ledger
            WHERE user_id=CAST(:u AS UUID) AND entry_date=:d
        """), {"u": uid, "d": body.entry_date})).first()
    return {"ok": True, "entry_date": body.entry_date.isoformat(),
            "daily_pnl": float(r[0]) if r else 0, "is_baseline": bool(r[1]) if r else False}


@router.delete("/entries/{entry_date}")
async def delete_entry(entry_date: date, ctx: ViewContext = Depends(get_view_context)):
    _deny_sub(ctx)
    uid = str(ctx.auth_user_id)
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            DELETE FROM manual_ledger WHERE user_id=CAST(:u AS UUID) AND entry_date=:d
        """), {"u": uid, "d": entry_date})
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="该日期无记录")
        await _recompute_chain(db, uid)
        await db.commit()
    return {"ok": True}
