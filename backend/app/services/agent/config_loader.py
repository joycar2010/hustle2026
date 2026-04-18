"""Hot-reloadable config with per-target overlay (P4.1).

Two layers:
  1. agent_active_config       — global baseline (all targets inherit)
  2. agent_target_config       — per-target overrides applied by approved proposals

When a target_id is provided, the caller gets merged_config = global ⟵ target_override.
Deep-merged per top-level key: target overlay entirely replaces a given key.

Cache: 5s LRU, separate entry per (None, target_id). Invalidated on approve/reject.
"""
import time
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_global_cache: Dict[str, Any] = {}
_global_ts: float = 0.0
_target_cache: Dict[int, tuple] = {}    # target_id → (overrides, ts)
_TTL = 5.0


async def _load_global(db: AsyncSession, force: bool = False) -> Dict[str, Any]:
    global _global_cache, _global_ts
    now = time.time()
    if not force and _global_cache and now - _global_ts < _TTL:
        return _global_cache
    rows = (await db.execute(text('SELECT key, value FROM agent_active_config'))).all()
    _global_cache = {k: v for k, v in rows}
    _global_ts = now
    return _global_cache


async def _load_target(db: AsyncSession, target_id: int, force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and target_id in _target_cache and now - _target_cache[target_id][1] < _TTL:
        return _target_cache[target_id][0]
    rows = (await db.execute(text(
        'SELECT key, value FROM agent_target_config WHERE target_id = :t'
    ), {'t': target_id})).all()
    overrides = {k: v for k, v in rows}
    _target_cache[target_id] = (overrides, now)
    return overrides


async def load_config(db: AsyncSession, force: bool = False,
                      target_id: Optional[int] = None) -> Dict[str, Any]:
    """Return effective config. If target_id set, per-target overrides overlay the global.

    The overlay is a top-level key replacement (not deep merge) so that approve-proposal
    with a `position_caps` diff replaces the whole caps dict for that target only.
    """
    base = await _load_global(db, force=force)
    if target_id is None:
        return base
    overrides = await _load_target(db, target_id, force=force)
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged


def invalidate(target_id: Optional[int] = None):
    """Invalidate global cache, and optionally a specific target overlay."""
    global _global_ts
    _global_ts = 0.0
    if target_id is not None:
        _target_cache.pop(target_id, None)
    else:
        _target_cache.clear()
