"""开市后自动恢复服务: 仅恢复"开市前确实在运行、且被收盘闸自动停掉"的连续策略,
按交易对预热(XAU 1min / ICXAU 2min)放行。硬约束: 开市前未运行的按钮永不被打开。

机制:
- 启动按钮时记录快照(record_start_snapshot), 供恢复时原样回放。
- 收盘闸自动停时(且仅此一处)打"待恢复"标(mark_resume_pending), 带3天TTL防隔日误恢复。
- 手动停时清标+清快照(clear_on_manual_stop_by_strategy_id), 故手动停的不会被恢复。
- StrategyResumeMonitor 每30s: 开市中, 对每个待恢复项, 若开市已满本对预热分钟、当前未在跑、
  且快照存在, 则用快照回放对应启动端点; 成功后清标。
"""
import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_PENDING_PREFIX = "strategy_resume_pending:"
_SNAPSHOT_PREFIX = "strategy_resume_snapshot:"
_PENDING_TTL = 3 * 24 * 3600
_FLAG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "strategy_resume.json")

_VALID_ACTIONS = ("reverse_opening", "forward_opening", "reverse_closing", "forward_closing")


def _member(user_id, pair_code, action):
    return str(user_id) + "|" + str(pair_code) + "|" + str(action)


def _split(member):
    parts = member.split("|")
    if len(parts) != 3:
        return (None, None, None)
    return (parts[0], parts[1], parts[2])


def strategy_id_for(user_id, pair_code, action):
    return str(user_id) + "_" + str(pair_code) + "_" + str(action) + "_continuous"


def _parse_strategy_id(strategy_id):
    suffix = "_continuous"
    if not strategy_id or not strategy_id.endswith(suffix):
        return (None, None, None)
    core = strategy_id[: -len(suffix)]
    parts = core.split("_")
    if len(parts) < 4:
        return (None, None, None)
    phase = parts[-1]
    typ = parts[-2]
    pair = parts[-3]
    user = "_".join(parts[:-3])
    return (user, pair, typ + "_" + phase)


def is_enabled():
    try:
        with open(_FLAG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("enabled", True))
    except Exception:
        return True


async def _rc():
    from app.core.redis_client import redis_client
    return redis_client


async def record_start_snapshot(user_id, pair_code, action, request_obj):
    """按钮启动成功后调用: 记录启动快照(原样回放用)。"""
    try:
        rc = await _rc()
        if hasattr(request_obj, "json"):
            payload = request_obj.json()
        elif hasattr(request_obj, "model_dump_json"):
            payload = request_obj.model_dump_json()
        else:
            payload = json.dumps(dict(request_obj))
        await rc.set(_SNAPSHOT_PREFIX + _member(user_id, pair_code, action), payload)
    except Exception as e:
        logger.warning("[RESUME] record snapshot failed " + _member(user_id, pair_code, action) + ": " + str(e))


async def mark_resume_pending(user_id, pair_code, action):
    """收盘闸自动停时调用(仅此一处打标): 标记该按钮待开市后恢复。"""
    try:
        rc = await _rc()
        await rc.set(_PENDING_PREFIX + _member(user_id, pair_code, action), str(time.time()), ex=_PENDING_TTL)
        logger.info("[RESUME] marked pending " + _member(user_id, pair_code, action))
    except Exception as e:
        logger.warning("[RESUME] mark pending failed: " + str(e))


async def clear_pending(user_id, pair_code, action):
    try:
        rc = await _rc()
        await rc.delete(_PENDING_PREFIX + _member(user_id, pair_code, action))
    except Exception as e:
        logger.warning("[RESUME] clear pending failed: " + str(e))


async def clear_on_manual_stop_by_strategy_id(strategy_id):
    """手动停端点调用: 按 strategy_id 清掉 pending+snapshot, 使手动停不被恢复。"""
    user, pair, action = _parse_strategy_id(strategy_id)
    if not user:
        return
    try:
        rc = await _rc()
        m = _member(user, pair, action)
        await rc.delete(_PENDING_PREFIX + m)
        await rc.delete(_SNAPSHOT_PREFIX + m)
        logger.info("[RESUME] cleared (manual stop) " + m)
    except Exception as e:
        logger.warning("[RESUME] clear on manual stop failed: " + str(e))


async def _replay_launch(user_id, pair_code, action, payload_json):
    from app.core.database import AsyncSessionLocal
    direction = "reverse" if action.startswith("reverse") else "forward"
    phase = "opening" if action.endswith("opening") else "closing"
    try:
        payload = json.loads(payload_json)
        async with AsyncSessionLocal() as db:
            if phase == "opening":
                from app.api.v1.strategies import execute_continuous_opening, ContinuousExecuteRequest
                req = ContinuousExecuteRequest(**payload)
                res = await execute_continuous_opening(strategy_type=direction, request=req, user_id=str(user_id), db=db)
            else:
                from app.api.v1.strategies import execute_continuous_closing, ContinuousClosingRequest
                req = ContinuousClosingRequest(**payload)
                res = await execute_continuous_closing(strategy_type=direction, request=req, user_id=str(user_id), db=db)
        ok = bool(res and isinstance(res, dict) and res.get("success"))
        if not ok:
            logger.warning("[RESUME] replay not success " + _member(user_id, pair_code, action) + ": " + str(res)[:200])
        return ok
    except Exception as e:
        logger.error("[RESUME] replay launch failed " + _member(user_id, pair_code, action) + ": " + str(e))
        return False


async def _try_resume_one(member):
    from app.utils.trading_time import (
        is_bybit_trading_hours, minutes_since_mt5_open, open_warmup_minutes,
        minutes_to_mt5_close, SOFT_STOP_BUFFER_MIN,
    )
    from app.services.execution_task_manager import execution_task_manager
    user_id, pair_code, action = _split(member)
    if not user_id or action not in _VALID_ACTIONS:
        return
    sid = strategy_id_for(user_id, pair_code, action)
    try:
        if execution_task_manager.get_running_task_id_for_strategy(sid):
            await clear_pending(user_id, pair_code, action)
            return
    except Exception:
        pass
    is_open, _ = is_bybit_trading_hours()
    if not is_open:
        return
    # 收盘前缓冲期闸门(2026-06-18新增): continuous_executor 的软/硬停在此窗口内
    # 主动停掉策略，是夏令时强制的安全停止点；is_bybit_trading_hours() 在窗口内仍判"开市"，
    # 若不在此拦截，本函数会在软停后的下一次30s巡检里把刚停掉的策略原样拉回(实测仅隔15秒)。
    # pending 标记保留不清，等真正越过收盘缓冲期后再按下方"开市+预热"逻辑自动恢复，
    # 此闸门内唯一能启动策略的途径只剩用户手动点击(execute_continuous_* 的另一调用方)。
    try:
        _mtc = minutes_to_mt5_close()
    except Exception:
        _mtc = None
    if _mtc is not None and _mtc <= SOFT_STOP_BUFFER_MIN:
        return
    so = minutes_since_mt5_open()
    wm = open_warmup_minutes(pair_code)
    if so is None or so < wm:
        return
    rc = await _rc()
    snap = await rc.get(_SNAPSHOT_PREFIX + member)
    if not snap:
        logger.warning("[RESUME] no snapshot for " + member + ", skip (no guess-launch)")
        await clear_pending(user_id, pair_code, action)
        return
    ok = await _replay_launch(user_id, pair_code, action, snap)
    if ok:
        await clear_pending(user_id, pair_code, action)
        logger.info("[RESUME] resumed " + member + " (open " + str(round(so, 1)) + "min >= " + str(wm) + "min)")


class StrategyResumeMonitor:
    """每30s 扫描待恢复项, 开市+预热到点后回放启动。"""

    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 30

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("[StrategyResumeMonitor] started (interval=30s)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self.running:
            try:
                if is_enabled():
                    await self._scan_once()
            except Exception as e:
                logger.error("[StrategyResumeMonitor] loop error: " + str(e))
            await asyncio.sleep(self.interval)

    async def _scan_once(self):
        rc = await _rc()
        raw = getattr(rc, "client", None)
        if raw is None:
            return
        members = []
        try:
            async for key in raw.scan_iter(match=_PENDING_PREFIX + "*"):
                k = key.decode() if isinstance(key, (bytes, bytearray)) else key
                members.append(k[len(_PENDING_PREFIX):])
        except Exception as e:
            logger.error("[StrategyResumeMonitor] scan failed: " + str(e))
            return
        for m in members:
            try:
                await _try_resume_one(m)
            except Exception as e:
                logger.error("[RESUME] resume one error " + m + ": " + str(e))


strategy_resume_monitor = StrategyResumeMonitor()
