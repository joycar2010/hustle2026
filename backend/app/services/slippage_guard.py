"""Slippage Guard — 滑点保护状态机.

设计:
- Per (user_id, pair_code) 独立状态
- Level 1: |s| > 0.9 单次触发, 暂停 10 分钟自动恢复
- Level 2: |s| > 1.2 连续 2 次触发 (或 Level 1 暂停期间再次 |s| > 1.2 升级),
  无自动恢复, 需用户 force_resume
- Redis 存储 + 关键事件写库 (slippage_events 表)
"""
from __future__ import annotations
import json
import logging
import time
from typing import Optional, Tuple, Dict
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)

LEVEL_1_THRESHOLD = 1.2
LEVEL_2_THRESHOLD = 1.5
AUTO_RESUME_S = 180  # 3 minutes
L2_CONSEC_REQUIRED = 4  # |s|>L2 连续达此次数才触发二级暂停(原为2次)
REDIS_TTL = 86400    # 24 hours

# Redis key format:
#   slippage_pause:{user_id}:{pair_code}    = JSON state
#   slippage_consec:{user_id}:{pair_code}   = INT consecutive Level-2 count


def _pause_key(user_id: str, pair_code: str) -> str:
    return f"slippage_pause:{user_id}:{pair_code}"


def _consec_key(user_id: str, pair_code: str) -> str:
    return f"slippage_consec:{user_id}:{pair_code}"


async def _get_redis():
    from app.core.redis_client import redis_client
    return redis_client.client


async def record_and_check(
    user_id: str,
    pair_code: str,
    strategy_type: str,
    spread_threshold: float,
    actual_spread: float,
    slippage: float,
    binance_order_id: Optional[str] = None,
    binance_avg_price: Optional[float] = None,
    bybit_avg_price: Optional[float] = None,
) -> Optional[Dict]:
    """每次双边成交后调用, 根据滑点决定是否触发暂停.

    Returns:
        触发暂停时返回 dict {"level": int, "reason": str, ...},
        否则返回 None.
    """
    if not user_id:
        return None
    abs_slip = abs(slippage)
    redis_cli = await _get_redis()

    triggered_level = None

    # Level 2 candidate: |s| > 1.2
    if abs_slip > LEVEL_2_THRESHOLD:
        cur = await redis_cli.get(_consec_key(user_id, pair_code))
        consec = int(cur) + 1 if cur else 1
        await redis_cli.setex(_consec_key(user_id, pair_code), REDIS_TTL, consec)
        logger.warning(
            f"[SLIPPAGE_GUARD] |s|={abs_slip:.4f} > L2={LEVEL_2_THRESHOLD} "
            f"user={user_id} pair={pair_code} consecutive={consec}"
        )

        # 升级触发: 已有 Level 1 暂停 → 直接升级 Level 2
        existing = await get_pause_state(user_id, pair_code)
        if existing and existing.get("level") == 1:
            triggered_level = 2
            logger.warning(f"[SLIPPAGE_GUARD] L1 → L2 upgrade triggered")
        elif consec >= L2_CONSEC_REQUIRED:
            triggered_level = 2

    # Level 1: 0.9 < |s| <= 1.2
    elif abs_slip > LEVEL_1_THRESHOLD:
        # 清零 L2 计数器 (因为这次不是 L2)
        await redis_cli.delete(_consec_key(user_id, pair_code))
        logger.warning(
            f"[SLIPPAGE_GUARD] |s|={abs_slip:.4f} > L1={LEVEL_1_THRESHOLD} "
            f"user={user_id} pair={pair_code}"
        )
        # 仅当当前无 L2 暂停时, 才触发 L1 (避免 L2 被降级)
        existing = await get_pause_state(user_id, pair_code)
        if not existing or existing.get("level") != 2:
            triggered_level = 1
    else:
        # |s| <= 0.9: 清零连续计数
        await redis_cli.delete(_consec_key(user_id, pair_code))

    if triggered_level is None:
        return None

    # 写入暂停状态
    now_ts = int(time.time())
    state = {
        "level": triggered_level,
        "reason": (
            f"单次滑点{abs_slip:.4f} > {LEVEL_1_THRESHOLD}" if triggered_level == 1
            else f"连续{L2_CONSEC_REQUIRED}次滑点超过{LEVEL_2_THRESHOLD} (本次={abs_slip:.4f})"
        ),
        "trigger_time": now_ts,
        "auto_resume_at": (now_ts + AUTO_RESUME_S) if triggered_level == 1 else None,
        "user_interacted": False,
        "pair_code": pair_code,
        "strategy_type": strategy_type,
        "slippage": round(slippage, 4),
        "actual_spread": round(actual_spread, 4),
        "threshold": spread_threshold,
    }
    await redis_cli.setex(
        _pause_key(user_id, pair_code),
        REDIS_TTL,
        json.dumps(state, default=str),
    )

    # 实时推送弹框事件: 经 ws:user_event -> rust-engine send_to_user -> 前端 SlippagePauseModal
    # (二级暂停需用户「确认(强制恢复)/取消(停止)」; 一级也推, 前端只对 level==2 阻断弹框)
    try:
        await redis_cli.publish("ws:user_event", json.dumps(
            {"user_id": str(user_id), "type": "slippage_pause", "data": state},
            default=str, ensure_ascii=False))
    except Exception as _pe:
        logger.warning(f"[SLIPPAGE_GUARD] ws push failed: {_pe}")

    # 写入审计表 + 发送飞书 (异步, 不阻塞 executor)
    import asyncio as _asyncio
    _asyncio.create_task(_write_event_and_notify(
        user_id=user_id,
        pair_code=pair_code,
        strategy_type=strategy_type,
        spread_threshold=spread_threshold,
        actual_spread=actual_spread,
        slippage=slippage,
        level=triggered_level,
        binance_order_id=binance_order_id,
        binance_avg_price=binance_avg_price,
        bybit_avg_price=bybit_avg_price,
    ))

    return state


async def _write_event_and_notify(
    user_id, pair_code, strategy_type, spread_threshold,
    actual_spread, slippage, level,
    binance_order_id, binance_avg_price, bybit_avg_price,
):
    # 1. 写库 (slippage_events)
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "INSERT INTO slippage_events "
                    "(user_id, pair_code, strategy_type, spread_threshold, "
                    " actual_spread, slippage, level, "
                    " binance_order_id, binance_avg_price, bybit_avg_price) "
                    "VALUES (:uid, :pc, :st, :th, :sp, :sl, :lv, :oid, :bap, :bbp)"
                ),
                {
                    "uid": UUID(user_id) if isinstance(user_id, str) else user_id,
                    "pc": pair_code,
                    "st": strategy_type,
                    "th": spread_threshold,
                    "sp": actual_spread,
                    "sl": slippage,
                    "lv": level,
                    "oid": str(binance_order_id) if binance_order_id is not None else None,  # 列为 varchar, 币安order_id是int必须转str(否则asyncpg DataError整条写库失败)
                    "bap": binance_avg_price,
                    "bbp": bybit_avg_price,
                },
            )
            await db.commit()
    except Exception as e:
        logger.error(f"[SLIPPAGE_GUARD] failed to write event: {e}")

    # 2. 发送飞书
    # 修(20260622): RiskAlertService 无模块级单例(只有类,需传 db 构造),原 `import risk_alert_service`
    # 恒报 ImportError 致滑点告警从不发出。改为 RiskAlertService(db) 实例化(与 broadcast_tasks 同口径)。
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.risk_alert_service import RiskAlertService
        template_key = (
            "slippage_warning_alert" if level == 1 else "slippage_critical_alert"
        )
        async with AsyncSessionLocal() as db:
            await RiskAlertService(db)._send_alert(
                user_id=user_id,
                template_key=template_key,
                variables={
                    "pair_code": pair_code,
                    "strategy_type": strategy_type,
                    "threshold": f"{spread_threshold:.4f}" if spread_threshold else "0",
                    "actual_spread": f"{actual_spread:.4f}",
                    "slippage": f"{slippage:.4f}",
                },
            )
    except Exception as e:
        logger.error(f"[SLIPPAGE_GUARD] feishu notify failed: {e}")


async def get_pause_state(user_id: str, pair_code: str) -> Optional[Dict]:
    """查询当前暂停状态, 返回 None 表示未暂停."""
    if not user_id:
        return None
    redis_cli = await _get_redis()
    raw = await redis_cli.get(_pause_key(user_id, pair_code))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def is_paused(user_id: str, pair_code: str) -> Tuple[bool, Optional[Dict]]:
    """启动策略前 / 网关每单检查. L1 到点(auto_resume_at)且用户未交互 -> 按需自动恢复.
    (原后台 auto_resume_tick worker 因 app 用 lifespan、@app.on_event(startup) 被忽略而从未启动, 此处兜底自愈.)"""
    state = await get_pause_state(user_id, pair_code)
    if state is None:
        return (False, None)
    if state.get("level") == 1 and not state.get("user_interacted"):
        _auto_at = state.get("auto_resume_at")
        if _auto_at and int(time.time()) >= int(_auto_at):
            await force_clear(user_id, pair_code, reason="auto_resume_expired_on_check")
            return (False, None)
    return (True, state)


async def mark_user_interaction(user_id: str, pair_code: str) -> None:
    """用户点击 4 按钮但被拒绝时调用 → 标记 user_interacted (取消自动恢复)."""
    state = await get_pause_state(user_id, pair_code)
    if not state:
        return
    state["user_interacted"] = True
    state["auto_resume_at"] = None  # 取消自动恢复
    state["last_interaction_at"] = int(time.time())
    redis_cli = await _get_redis()
    await redis_cli.setex(
        _pause_key(user_id, pair_code),
        REDIS_TTL,
        json.dumps(state, default=str),
    )
    logger.info(f"[SLIPPAGE_GUARD] user interaction recorded — auto_resume cancelled user={user_id} pair={pair_code}")


async def force_clear(user_id: str, pair_code: str, reason: str = "user_force_resume") -> None:
    """用户点 force_resume → 清除暂停状态 (不清除 L2 连续计数, 避免短时间再触发)."""
    redis_cli = await _get_redis()
    await redis_cli.delete(_pause_key(user_id, pair_code))
    logger.info(f"[SLIPPAGE_GUARD] pause cleared user={user_id} pair={pair_code} reason={reason}")


async def auto_resume_tick() -> int:
    """后台任务: 扫描所有暂停状态, 自动恢复 L1 中未交互的.

    Returns 已恢复的暂停数量.
    """
    redis_cli = await _get_redis()
    resumed = 0
    try:
        # SCAN 比 KEYS 更安全
        cursor = 0
        now_ts = int(time.time())
        while True:
            cursor, keys = await redis_cli.scan(
                cursor=cursor, match="slippage_pause:*", count=100
            )
            for key in keys:
                try:
                    raw = await redis_cli.get(key)
                    if not raw:
                        continue
                    state = json.loads(raw)
                    if state.get("user_interacted"):
                        continue
                    if state.get("level") != 1:
                        continue
                    auto_at = state.get("auto_resume_at")
                    if not auto_at or now_ts < int(auto_at):
                        continue
                    await redis_cli.delete(key)
                    resumed += 1
                    logger.info(f"[SLIPPAGE_GUARD] auto-resumed key={key}")
                except Exception as _e:
                    logger.debug(f"[SLIPPAGE_GUARD] tick item error: {_e}")
            if cursor == 0:
                break
    except Exception as e:
        logger.error(f"[SLIPPAGE_GUARD] auto_resume_tick error: {e}")
    return resumed


async def query_events(
    user_id: Optional[str] = None,
    pair_code: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """查询滑点事件 (供 SpreadChart 审计展示)."""
    from app.core.database import AsyncSessionLocal
    conditions = []
    params = {"limit": limit, "offset": offset}
    if user_id:
        conditions.append("user_id = :uid")
        params["uid"] = UUID(user_id) if isinstance(user_id, str) else user_id
    if pair_code:
        conditions.append("pair_code = :pc")
        params["pc"] = pair_code
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = (
        "SELECT id, user_id, pair_code, strategy_type, spread_threshold, "
        "actual_spread, slippage, level, binance_order_id, "
        "binance_avg_price, bybit_avg_price, created_at "
        f"FROM slippage_events {where} "
        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    )
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(sql), params)).mappings().all()
        return [dict(r) for r in rows]
