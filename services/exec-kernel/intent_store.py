"""
Intent 持久化扩展 - store.py 补充
关4 Phase D: Intent 审计追踪
"""
import json


async def save_intent(pool, intent):
    """
    持久化 Intent 到 exec_intent 表
    Args:
        pool: asyncpg connection pool
        intent: Intent 对象(OpenPairIntent/ClosePairIntent/RebalanceIntent/etc.)
    Returns:
        intent_id
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO exec_intent (
                intent_id, intent_type, created_at, pair_id, symbol,
                venue_long, venue_short, target_notional_usdt,
                current_notional_usdt, reason, payload
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            ON CONFLICT (intent_id) DO NOTHING
            """,
            intent.intent_id,
            intent.intent_type.value if hasattr(intent.intent_type, 'value') else str(intent.intent_type),
            intent.created_at,
            getattr(intent, 'pair_id', None),
            getattr(intent, 'symbol', None),
            getattr(intent, 'venue_long', None),
            getattr(intent, 'venue_short', None),
            getattr(intent, 'target_notional_usdt', None),
            getattr(intent, 'current_notional_usdt', None),
            intent.reason,
            json.dumps(intent.to_dict(), ensure_ascii=False),
        )
    return intent.intent_id


async def link_saga_to_intent(pool, saga_id: str, intent_id: str):
    """
    关联 Saga 到 Intent(exec_saga.intent_id)
    Args:
        pool: asyncpg connection pool
        saga_id: Saga ID
        intent_id: Intent ID
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE exec_saga SET intent_id = $1 WHERE saga_id = $2",
            intent_id, saga_id
        )


async def get_intent_by_id(pool, intent_id: str):
    """
    根据 intent_id 查询 Intent
    Returns:
        dict or None
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM exec_intent WHERE intent_id = $1",
            intent_id
        )
        return dict(row) if row else None


async def list_recent_intents(pool, limit: int = 100):
    """
    列出最近的 Intent(按创建时间倒序)
    Returns:
        List[dict]
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT intent_id, intent_type, created_at, pair_id, symbol,
                   venue_long, venue_short, reason, created_at_ts
            FROM exec_intent
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit
        )
        return [dict(r) for r in rows]


async def get_saga_with_intent(pool, saga_id: str):
    """
    查询 Saga 及其关联的 Intent
    Returns:
        dict with saga and intent fields
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                s.saga_id, s.state, s.intent_id,
                i.intent_type, i.pair_id, i.reason as intent_reason
            FROM exec_saga s
            LEFT JOIN exec_intent i ON s.intent_id = i.intent_id
            WHERE s.saga_id = $1
            """,
            saga_id
        )
        return dict(row) if row else None


# 统计函数
async def intent_stats(pool):
    """
    Intent 统计(按类型分组)
    Returns:
        List[dict]: [{"intent_type": "OPEN_PAIR", "count": 10}, ...]
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT intent_type, COUNT(*) as count
            FROM exec_intent
            GROUP BY intent_type
            ORDER BY count DESC
            """
        )
        return [dict(r) for r in rows]


async def saga_intent_coverage(pool):
    """
    Saga Intent 覆盖率统计
    Returns:
        dict: {"total_sagas": N, "with_intent": M, "coverage_pct": X}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_sagas,
                COUNT(intent_id) as with_intent,
                ROUND(100.0 * COUNT(intent_id) / NULLIF(COUNT(*), 0), 2) as coverage_pct
            FROM exec_saga
            """
        )
        return dict(row) if row else {"total_sagas": 0, "with_intent": 0, "coverage_pct": 0.0}
