"""Scope resolver — multi-target, per-user isolation.

P4.0 model: agent_scope_targets table holds N rows of (user_id, pair_code, enabled).
Each row is an independent execution target. The agent loop iterates over all
enabled targets every tick and calls decide(db, trigger, target) for each.

Strict isolation per target:
  - Positions/equity:  only accounts belonging to target.user_id on the pair's platforms
  - Rate buckets:      namespaced by (user_id, pair_code) so one target cannot deplete
                       another's anti-ban budget
  - Decisions:         tagged with scope_user_id/scope_pair_code/scope_target_id
  - Equity FSM:        state scoped to target_id (stored in equity_intervention_log.scope_target_id)
  - Feishu broadcast:  messages prefixed with [user/pair] for attribution

Legacy agent_scope key is kept only as a seed during migration; it is no longer
consulted at runtime. ScopeContext now always carries target_id.
"""
import time
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account

logger = logging.getLogger(__name__)

_ctx_cache: dict = {}       # target_id → (ScopeContext, ts)
_targets_cache = None       # (list[dict], ts)
_TTL = 5.0


@dataclass
class ScopeContext:
    target_id: int
    user_id: str
    username: str
    pair_code: str
    a_platform_id: int
    b_platform_id: int
    a_symbol: str
    b_symbol: str
    conversion_factor: float
    a_account_id: Optional[str]
    b_account_id: Optional[str]

    @property
    def rate_namespace(self) -> str:
        """Key prefix for per-target rate-limit buckets."""
        return f'openclaw:rate:t{self.target_id}'

    @property
    def label(self) -> str:
        return f'{self.username}/{self.pair_code}'

    def is_scope_match_account(self, acc: Account) -> bool:
        if str(acc.user_id) != str(self.user_id):
            return False
        if self.a_account_id and str(acc.account_id) == self.a_account_id:
            return True
        if self.b_account_id and str(acc.account_id) == self.b_account_id:
            return True
        if not self.a_account_id and not self.b_account_id:
            return acc.platform_id in (self.a_platform_id, self.b_platform_id)
        return False


async def list_target_rows(db: AsyncSession, enabled_only: bool = True) -> List[dict]:
    """Raw list of target rows (no resolution). Cached 5s."""
    global _targets_cache
    if _targets_cache and time.time() - _targets_cache[1] < _TTL:
        rows = _targets_cache[0]
    else:
        sql = """
          SELECT t.id, t.user_id::text, u.username, t.pair_code, t.enabled, t.priority,
                 t.created_at, t.updated_at
          FROM agent_scope_targets t
          JOIN users u ON u.user_id = t.user_id
          ORDER BY t.priority DESC, t.id
        """
        res = (await db.execute(text(sql))).all()
        rows = [{'id': r[0], 'user_id': r[1], 'username': r[2], 'pair_code': r[3],
                 'enabled': r[4], 'priority': r[5],
                 'created_at': r[6].isoformat() if r[6] else None,
                 'updated_at': r[7].isoformat() if r[7] else None} for r in res]
        _targets_cache = (rows, time.time())
    if enabled_only:
        return [r for r in rows if r['enabled']]
    return rows


async def resolve_target(db: AsyncSession, target_row: dict, force: bool = False) -> Optional[ScopeContext]:
    """Build a ScopeContext from one target row. Cached 5s per target_id."""
    tid = target_row['id']
    if not force and tid in _ctx_cache and time.time() - _ctx_cache[tid][1] < _TTL:
        return _ctx_cache[tid][0]

    row = (await db.execute(text("""
        SELECT hp.conversion_factor, hp.account_a_id, hp.account_b_id,
               sa.platform_id, sa.symbol, sb.platform_id, sb.symbol
        FROM hedging_pairs hp
        JOIN platform_symbols sa ON sa.id = hp.symbol_a_id
        JOIN platform_symbols sb ON sb.id = hp.symbol_b_id
        WHERE hp.pair_code = :c AND hp.is_active = true
        LIMIT 1
    """), {'c': target_row['pair_code']})).first()
    if not row:
        logger.warning(f'[scope] pair {target_row["pair_code"]} not found for target #{tid}')
        return None

    conv, a_pin, b_pin, pa, sya, pb, syb = row
    a_account_id = str(a_pin) if a_pin else None
    b_account_id = str(b_pin) if b_pin else None

    # user_pair_accounts override
    ur = (await db.execute(text("""
        SELECT account_a_id, account_b_id FROM user_pair_accounts
        WHERE user_id = CAST(:u AS UUID) AND pair_code = :c LIMIT 1
    """), {'u': target_row['user_id'], 'c': target_row['pair_code']})).first()
    if ur:
        if ur[0]: a_account_id = str(ur[0])
        if ur[1]: b_account_id = str(ur[1])

    ctx = ScopeContext(
        target_id=tid, user_id=target_row['user_id'], username=target_row['username'],
        pair_code=target_row['pair_code'],
        a_platform_id=int(pa), b_platform_id=int(pb),
        a_symbol=sya, b_symbol=syb,
        conversion_factor=float(conv or 100.0),
        a_account_id=a_account_id, b_account_id=b_account_id,
    )
    _ctx_cache[tid] = (ctx, time.time())
    return ctx


async def list_active_contexts(db: AsyncSession) -> List[ScopeContext]:
    """All enabled targets, fully resolved. Main entry point for the agent loop."""
    rows = await list_target_rows(db, enabled_only=True)
    out: List[ScopeContext] = []
    for r in rows:
        c = await resolve_target(db, r)
        if c:
            out.append(c)
    return out


async def resolve_a_b_accounts(db: AsyncSession, ctx: ScopeContext) -> Tuple[Optional[Account], Optional[Account]]:
    """Pick A/B accounts that belong to the target."""
    accs = (await db.execute(
        select(Account).where(Account.is_active == True, Account.user_id == ctx.user_id)
    )).scalars().all()

    def _match_a(a):
        if ctx.a_account_id: return str(a.account_id) == ctx.a_account_id
        return a.platform_id == ctx.a_platform_id and not a.is_mt5_account

    def _match_b(a):
        if ctx.b_account_id: return str(a.account_id) == ctx.b_account_id
        return a.platform_id == ctx.b_platform_id and a.is_mt5_account

    return next((a for a in accs if _match_a(a)), None), next((a for a in accs if _match_b(a)), None)


def invalidate():
    global _ctx_cache, _targets_cache
    _ctx_cache = {}
    _targets_cache = None


# ───── CRUD helpers (used by API) ─────

async def create_target(db: AsyncSession, user_id: str, pair_code: str, priority: int = 0) -> int:
    res = await db.execute(text("""
        INSERT INTO agent_scope_targets (user_id, pair_code, priority)
        VALUES (CAST(:u AS UUID), :c, :p)
        ON CONFLICT (user_id, pair_code) DO UPDATE
          SET enabled = TRUE, priority = EXCLUDED.priority, updated_at = NOW()
        RETURNING id
    """), {'u': user_id, 'c': pair_code, 'p': priority})
    new_id = res.scalar_one()
    await db.commit()
    invalidate()
    return new_id


async def delete_target(db: AsyncSession, target_id: int) -> bool:
    r = await db.execute(text("DELETE FROM agent_scope_targets WHERE id = :i"), {'i': target_id})
    await db.commit()
    invalidate()
    return r.rowcount > 0


async def toggle_target(db: AsyncSession, target_id: int, enabled: bool) -> bool:
    r = await db.execute(text("""
        UPDATE agent_scope_targets SET enabled = :e, updated_at = NOW() WHERE id = :i
    """), {'e': enabled, 'i': target_id})
    await db.commit()
    invalidate()
    return r.rowcount > 0
