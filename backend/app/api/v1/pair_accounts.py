"""Pair-Account binding API — maps user + pair_code to specific A/B accounts"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
from app.core.database import get_db
from app.core.security import get_current_user_id

router = APIRouter()


class PairAccountBinding(BaseModel):
    pair_code: str
    account_a_id: Optional[str] = None
    account_b_id: Optional[str] = None


class PairAccountResponse(BaseModel):
    pair_code: str
    account_a_id: Optional[str] = None
    account_a_name: Optional[str] = None
    account_b_id: Optional[str] = None
    account_b_name: Optional[str] = None


@router.get("/pair-accounts")
async def list_pair_accounts(
    user_id_param: str = Query(None, alias="user_id"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List all pair-account bindings for a user. Admin can query other users."""
    target_uid = user_id_param or user_id
    result = await db.execute(text("""
        SELECT upa.pair_code,
               upa.account_a_id::text, aa.account_name as a_name,
               upa.account_b_id::text, ab.account_name as b_name
        FROM user_pair_accounts upa
        LEFT JOIN accounts aa ON upa.account_a_id = aa.account_id
        LEFT JOIN accounts ab ON upa.account_b_id = ab.account_id
        WHERE upa.user_id = :uid
        ORDER BY upa.pair_code
    """), {"uid": target_uid})
    rows = result.fetchall()
    return [
        {"pair_code": r[0], "account_a_id": r[1], "account_a_name": r[2], "account_b_id": r[3], "account_b_name": r[4]}
        for r in rows
    ]


@router.get("/pair-accounts/{pair_code}")
async def get_pair_account(
    pair_code: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get pair-account binding for current user and specific pair."""
    result = await db.execute(text("""
        SELECT upa.account_a_id::text, aa.account_name, COALESCE(aa.is_active, true),
               upa.account_b_id::text, ab.account_name, COALESCE(ab.is_active, true)
        FROM user_pair_accounts upa
        LEFT JOIN accounts aa ON upa.account_a_id = aa.account_id
        LEFT JOIN accounts ab ON upa.account_b_id = ab.account_id
        WHERE upa.user_id = :uid AND upa.pair_code = :pc
    """), {"uid": user_id, "pc": pair_code})
    row = result.fetchone()
    if not row:
        return {"pair_code": pair_code, "account_a_id": None, "account_b_id": None}
    return {
        "pair_code": pair_code,
        "account_a_id": row[0], "account_a_name": row[1], "account_a_active": row[2],
        "account_b_id": row[3], "account_b_name": row[4], "account_b_active": row[5],
    }


@router.put("/pair-accounts")
async def upsert_pair_account(
    body: PairAccountBinding,
    user_id_param: str = Query(None, alias="user_id"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Set pair-account binding. Admin can set for other users via ?user_id="""
    target_uid = user_id_param or user_id

    # Use two-step: delete then insert (simpler than CASE WHEN with uuid cast)
    await db.execute(text(
        "DELETE FROM user_pair_accounts WHERE user_id = :uid AND pair_code = :pc"
    ), {"uid": target_uid, "pc": body.pair_code})

    aid = body.account_a_id if body.account_a_id else None
    bid = body.account_b_id if body.account_b_id else None

    if aid or bid:
        await db.execute(text("""
            INSERT INTO user_pair_accounts (user_id, pair_code, account_a_id, account_b_id, updated_at)
            VALUES (:uid, :pc, :aid, :bid, NOW())
        """), {"uid": target_uid, "pc": body.pair_code, "aid": aid, "bid": bid})
    await db.commit()
    return {"status": "ok", "pair_code": body.pair_code}


@router.delete("/pair-accounts/{pair_code}")
async def delete_pair_account(
    pair_code: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove pair-account binding."""
    await db.execute(text(
        "DELETE FROM user_pair_accounts WHERE user_id = :uid AND pair_code = :pc"
    ), {"uid": user_id, "pc": pair_code})
    await db.commit()
    return {"status": "deleted", "pair_code": pair_code}
