"""Trading Gateway — 全局下单守卫.

所有下单操作（策略 / 手动 / Agent 减仓）都必须经过此网关。
网关统一检查: mode / kill_switch / 滑点保护 / 限流等风控条件。

Usage:
    from app.services.trading_gateway import check_trading_allowed, TradingBlocked

    result = await check_trading_allowed(
        caller="equity_fsm",
        user_id="...",
        pair_code="XAU",
    )
    if not result.allowed:
        logger.warning(f"Trading blocked: {result.reason}")
        return  # abort
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GatewayResult:
    allowed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


class TradingBlocked(Exception):
    """Raised when trading is blocked by the gateway."""
    def __init__(self, result: GatewayResult):
        self.result = result
        super().__init__(result.reason)


async def _load_openclaw_state() -> dict:
    """Load OpenCLAW status from agent_active_config (cached 5s)."""
    now = time.time()
    if _state_cache["ts"] and now - _state_cache["ts"] < 5:
        return _state_cache["data"]
    try:
        from app.services.agent import config_loader
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            cfg = await config_loader.load_config(db)
        state = cfg.get("openclaw_status", {})
        _state_cache["data"] = state
        _state_cache["ts"] = now
        return state
    except Exception as e:
        logger.debug(f"[GATEWAY] config load failed: {e}")
        return _state_cache.get("data", {})

_state_cache = {"data": {}, "ts": 0}


async def is_trading_allowed(
    caller: str = "unknown",
    user_id: Optional[str] = None,
    pair_code: Optional[str] = None,
    force: bool = False,
) -> GatewayResult:
    """统一下单前置检查. 所有下单路径必须调用.

    Args:
        caller: 调用方标识 (equity_fsm / continuous_executor / manual / partial_reduce)
        user_id: 用户 ID (可选, 用于 per-user 检查)
        pair_code: 产品对 (可选, 用于 per-pair 检查)
        force: True = 跳过 slippage_pause 检查 (但 kill_switch/shadow 不可跳过)

    Returns:
        GatewayResult(allowed=True/False, reason=..., details=...)
    """
    details = {"caller": caller, "user_id": user_id, "pair_code": pair_code, "ts": time.time()}

    # ── 1. OpenCLAW mode / kill_switch (最高优先级, 不可跳过) ──
    state = await _load_openclaw_state()
    kill_switch = state.get("kill_switch", False)
    mode = state.get("mode", "shadow")
    openclaw_enabled = state.get("openclaw_enabled", True)

    if kill_switch:
        details["block"] = "kill_switch"
        logger.warning(f"[GATEWAY] BLOCKED by kill_switch | caller={caller} user={user_id} pair={pair_code}")
        return GatewayResult(allowed=False, reason="kill_switch 已激活, 所有交易已暂停", details=details)

    if mode in ("off", "shadow"):
        # shadow 模式: agent 组件 (equity_fsm / partial_reduce) 不可执行真实交易
        # 但手动交易 (manual) 和用户主动启动的策略 (continuous_executor) 允许
        if caller in ("equity_fsm", "partial_reduce", "agent_loop", "agent"):
            details["block"] = f"mode={mode}"
            logger.warning(f"[GATEWAY] BLOCKED agent caller={caller} in {mode} mode | user={user_id} pair={pair_code}")
            return GatewayResult(allowed=False, reason=f"OpenCLAW 处于 {mode} 模式, Agent 自动交易已禁用", details=details)

    if not openclaw_enabled and caller in ("equity_fsm", "partial_reduce", "agent_loop", "agent"):
        details["block"] = "openclaw_disabled"
        logger.warning(f"[GATEWAY] BLOCKED agent caller={caller} (openclaw disabled) | user={user_id} pair={pair_code}")
        return GatewayResult(allowed=False, reason="OpenCLAW 已关闭, Agent 自动交易已禁用", details=details)

    # ── 2. 滑点保护暂停 (可通过 force 跳过) ──
    if not force and user_id and pair_code:
        try:
            from app.services.slippage_guard import is_paused as _slip_paused
            paused, pause_state = await _slip_paused(user_id, pair_code)
            if paused:
                details["block"] = "slippage_paused"
                details["slippage_level"] = pause_state.get("level") if pause_state else None
                logger.warning(f"[GATEWAY] BLOCKED by slippage_pause | caller={caller} user={user_id} pair={pair_code}")
                return GatewayResult(
                    allowed=False,
                    reason=f"滑点保护已暂停交易 (level={pause_state.get('level')})",
                    details=details,
                )
        except Exception as e:
            logger.debug(f"[GATEWAY] slippage check failed (allowing): {e}")

    # ── 3. 通过 ──
    return GatewayResult(allowed=True, reason="", details=details)


async def check_and_raise(
    caller: str = "unknown",
    user_id: Optional[str] = None,
    pair_code: Optional[str] = None,
    force: bool = False,
) -> None:
    """Convenience: check + raise TradingBlocked if not allowed."""
    result = await is_trading_allowed(caller=caller, user_id=user_id, pair_code=pair_code, force=force)
    if not result.allowed:
        raise TradingBlocked(result)
