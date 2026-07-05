"""Strategy Process Monitor (admin, read-only) — P0.

Single cross-user, read-only window into the auto-ladder execution engine.
Joins THREE truth sources and reconciles them so the admin sees not just
"who is trading" but whether the three sources agree (mismatches = the
classic incidents: zombie / single-leg / naked-position / db-mismatch).

Truth sources (all in-memory / Redis — NO exchange calls, NO heavy SQL):
  1. ExecutionTaskManager.executors  -> a strategy PROCESS is actively running
  2. Redis strategy_active:{user}:*  -> the execution loop wrote its alive key
  3. PositionStreamer per-user-per-pair maps -> real positions held

The endpoint is intentionally cheap (target <50ms): it reads process memory
and a Redis SCAN only. Reconciliation is computed server-side so the front
end just renders flags.
"""
import logging
import time as _time
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}

# 心跳静默阈值(秒): 与 ExecutionTaskManager 看门狗/前端看门狗口径一致
HB_SILENT_S = 20.0
HB_ZOMBIE_S = 120.0


def _proc_state(executor, info: Dict[str, Any]) -> Dict[str, Any]:
    """Derive live process state from an executor + its task_info."""
    now = _time.monotonic()
    hb = getattr(executor, "_last_heartbeat", None)
    stale = None
    if hb is not None:
        stale = max(0.0, now - hb)
    status = info.get("status", "unknown")
    # 三态活性: running / silent(>20s) / zombie(>120s 仍 running)
    liveness = "running"
    if status in ("stalled", "cancelled", "failed", "completed"):
        liveness = status
    elif stale is not None and stale > HB_ZOMBIE_S:
        liveness = "zombie"
    elif stale is not None and stale > HB_SILENT_S:
        liveness = "silent"

    # ── P1: 阶梯进度 + 触发计数 + 组件健康灯(读真实可读信号,不杜撰) ──
    ladders = getattr(executor, "ladders", None)
    total_ladders = len(ladders) if isinstance(ladders, (list, tuple)) else None
    tm = getattr(executor, "trigger_mgr", None)
    trigger_count = getattr(tm, "count", None) if tm is not None else None

    # 组件健康: 每个子系统给 {state, detail}。state ∈ ok / warn / down / idle / unknown。
    # 只读已注入的引用是否存在 + 心跳新鲜度派生,绝不调用交易所/桥。
    fresh = (stale is not None and stale <= HB_SILENT_S)
    comp_loop = ("ok" if (liveness == "running" and fresh) else
                 ("warn" if liveness == "silent" else
                  ("down" if liveness in ("zombie", "stalled") else "idle")))
    components = {
        "execution_loop": {"state": comp_loop,
                           "detail": f"心跳 {round(stale,1)}s" if stale is not None else "未启动"},
        "trigger_manager": {"state": ("ok" if tm is not None else "idle"),
                            "detail": (f"累计 {trigger_count}" if trigger_count is not None else "未初始化")},
        "ladder_mapper": {"state": ("ok" if total_ladders else "idle"),
                         "detail": (f"阶 {getattr(executor,'current_ladder_index',0)}/{total_ladders}"
                                    if total_ladders else "无阶梯")},
        "order_executor": {"state": ("ok" if getattr(executor, "order_executor", None) is not None else "down"),
                          "detail": "已挂载" if getattr(executor, "order_executor", None) is not None else "缺失"},
        "position_manager": {"state": ("ok" if getattr(executor, "position_mgr", None) is not None else "down"),
                            "detail": "已挂载" if getattr(executor, "position_mgr", None) is not None else "缺失"},
        "status_pusher": {"state": "ok", "detail": "WS 推送"},
        "mt5_preflight": {"state": ("ok" if not getattr(executor, "stop_reason", None) else "warn"),
                         "detail": getattr(executor, "stop_reason", None) or "正常"},
        "redis_active_key": {"state": "ok" if getattr(executor, "_active_key", None) else "idle",
                            "detail": getattr(executor, "_active_key", None) or "无"},
    }

    return {
        "liveness": liveness,
        "status": status,
        "is_running": bool(getattr(executor, "is_running", False)),
        "heartbeat_age_s": round(stale, 1) if stale is not None else None,
        "current_ladder_index": getattr(executor, "current_ladder_index", None),
        "total_ladders": total_ladders,
        "trigger_count": trigger_count,
        "hedge_multiplier": getattr(executor, "hedge_multiplier", None),
        "stop_requested": bool(getattr(executor, "stop_requested", False)),
        "stop_reason": getattr(executor, "stop_reason", None),
        "started_at": info.get("started_at"),
        "components": components,
    }


@router.get("/strategies/processes")
async def get_strategy_processes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Admin-only cross-user view of all auto-ladder strategy processes,
    the active-key set, and live positions — reconciled into a user×pair
    matrix. Read-only; no exchange calls."""
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return await compute_process_snapshot(db)


async def compute_process_snapshot(db) -> Dict[str, Any]:
    """Shared core: build the user×pair process snapshot + reconciliation flags.
    Used by BOTH the admin endpoint and the reconciliation alerter, so the panel's
    red cells and the Feishu/WS alerts come from ONE computation (no口径 divergence)."""
    from app.services.execution_task_manager import execution_task_manager
    from app.services.strategy_resume_service import _parse_strategy_id

    # ── Source 1: process registry (per task) ───────────────────────────
    procs: List[Dict[str, Any]] = []
    # key: (user_id, pair_code) -> aggregated cell
    cells: Dict[tuple, Dict[str, Any]] = {}
    user_ids: set = set()

    all_info = execution_task_manager.get_all_tasks() or {}
    for task_id, info in all_info.items():
        if not info:
            continue
        executor = execution_task_manager.executors.get(task_id)
        if executor is None:
            continue
        uid = getattr(executor, "user_id", None) or ""
        pair = getattr(executor, "pair_code", None) or ""
        sid = info.get("strategy_id") or getattr(executor, "strategy_id", "")
        # parse direction/action from strategy_id (forward/reverse + opening/closing)
        _u, _p, action = _parse_strategy_id(sid or "")
        state = _proc_state(executor, info)
        rec = {
            "task_id": task_id,
            "strategy_id": sid,
            "user_id": uid,
            "pair_code": pair,
            "action": action,  # e.g. forward_opening / reverse_closing
            **state,
        }
        # only surface live-ish processes in the matrix (running/silent/zombie/stalled)
        procs.append(rec)
        if uid:
            user_ids.add(uid)
        if uid and pair:
            key = (uid, pair)
            cell = cells.setdefault(key, {
                "user_id": uid, "pair_code": pair,
                "processes": [], "active_keys": [], "positions": None,
                "reconcile_flags": [],
            })
            cell["processes"].append(rec)

    # ── Source 2: Redis active keys (loop-alive) ────────────────────────
    active_by_user: Dict[str, List[str]] = {}
    try:
        from app.core.redis_client import redis_client
        rc = redis_client.client
        if rc is not None:
            async for k in rc.scan_iter(match="strategy_active:*", count=200):
                # strategy_active:{user_id}:{direction}_{action}
                parts = (k if isinstance(k, str) else k.decode()).split(":")
                if len(parts) >= 3:
                    a_uid = parts[1]
                    active_by_user.setdefault(a_uid, []).append(":".join(parts[2:]))
                    user_ids.add(a_uid)
    except Exception as e:
        logger.warning(f"[proc-monitor] active key scan failed: {e}")

    # ── Source 2b (P2): Redis proc heartbeat hashes — cross-process/restart-proof.
    # strategy_proc:{user}:{dir}_{act} (ex=90s, written by executor every 30s). When a
    # process exists in Redis but NOT in this worker's in-memory registry (other worker /
    # post-restart), synthesize a process record so the admin still sees it.
    try:
        from app.core.redis_client import redis_client as _rc2
        from app.services.strategy_resume_service import _parse_strategy_id as _psi  # noqa
        rc2 = _rc2.client
        if rc2 is not None:
            mem_idents = {(p["user_id"], p.get("action") or "") for p in procs}
            async for k in rc2.scan_iter(match="strategy_proc:*", count=200):
                ks = k if isinstance(k, str) else k.decode()
                parts = ks.split(":")
                if len(parts) < 3:
                    continue
                r_uid = parts[1]
                dir_act = ":".join(parts[2:])  # e.g. reverse_opening
                if (r_uid, dir_act) in mem_idents:
                    continue  # already covered by in-memory (authoritative)
                try:
                    h = await rc2.hgetall(k)
                except Exception:
                    continue
                if not h:
                    continue
                def _gi(d, kk, dv=0):
                    try: return int(d.get(kk, dv))
                    except Exception: return dv
                import time as _t2
                hb_age = None
                try:
                    hb_age = max(0.0, _t2.time() - int(h.get("hb_ts", 0)))
                except Exception:
                    pass
                live = "running"
                if hb_age is not None and hb_age > HB_ZOMBIE_S:
                    live = "zombie"
                elif hb_age is not None and hb_age > HB_SILENT_S:
                    live = "silent"
                pc = h.get("pair_code") or ""
                rec = {
                    "task_id": None, "strategy_id": None,
                    "user_id": r_uid, "pair_code": pc, "action": dir_act,
                    "liveness": live, "status": "running",
                    "is_running": h.get("is_running") == "1",
                    "heartbeat_age_s": round(hb_age, 1) if hb_age is not None else None,
                    "current_ladder_index": _gi(h, "current_ladder_index"),
                    "total_ladders": _gi(h, "total_ladders"),
                    "trigger_count": _gi(h, "trigger_count"),
                    "hedge_multiplier": float(h.get("hedge_multiplier", 1.0) or 1.0),
                    "stop_requested": h.get("stop_requested") == "1",
                    "stop_reason": h.get("stop_reason") or None,
                    "started_at": None, "source": "redis",
                }
                procs.append(rec)
                user_ids.add(r_uid)
                if r_uid and pc:
                    cell = cells.setdefault((r_uid, pc), {
                        "user_id": r_uid, "pair_code": pc,
                        "processes": [], "active_keys": [], "positions": None,
                        "reconcile_flags": [],
                    })
                    cell["processes"].append(rec)
    except Exception as e:
        logger.warning(f"[proc-monitor] proc-hash scan failed: {e}")

    for (uid, pair), cell in cells.items():
        cell["active_keys"] = active_by_user.get(uid, [])

    # ── Source 3a: per-pair positions for PROCESS-ENGAGED pairs (authoritative) ──
    # _last_pairs_by_user fans the same position across all symbol-sharing pairs, so it is
    # ONLY trustworthy for a pair_code that a process/active-key actually names.
    pos_by_user_pair: Dict[str, Dict[str, Dict[str, float]]] = {}
    try:
        from app.tasks.broadcast_tasks import position_streamer as _ps
        src = getattr(_ps, "_last_pairs_by_user", {}) or {}
        for uid, per_pair in src.items():
            if uid == "_default":
                continue
            pos_by_user_pair[uid] = {pc: dict(pd) for pc, pd in per_pair.items()}
    except Exception as e:
        logger.warning(f"[proc-monitor] per-pair position read failed: {e}")

    # ── Source 3b: RAW per-symbol positions (no fan-out) for resting inventory ──
    # _mt5_lkg / _binance_positions: {user_id: {symbol: (long, short)}} — one row per symbol,
    # the unambiguous truth when no process owns the position.
    raw_sym_by_user: Dict[str, Dict[str, Any]] = {}
    try:
        from app.tasks.broadcast_tasks import position_streamer as _ps2
        mt5 = getattr(_ps2, "_mt5_lkg", {}) or {}
        bn = getattr(_ps2, "_binance_positions", {}) or {}
        for uid in set(list(mt5.keys()) + list(bn.keys())):
            if uid == "_default":
                continue
            mt5_long = sum((v[0] or 0) for v in (mt5.get(uid, {}) or {}).values())
            mt5_short = sum((v[1] or 0) for v in (mt5.get(uid, {}) or {}).values())
            bn_long = sum((v[0] or 0) for v in (bn.get(uid, {}) or {}).values())
            bn_short = sum((v[1] or 0) for v in (bn.get(uid, {}) or {}).values())
            if abs(mt5_long) + abs(mt5_short) + abs(bn_long) + abs(bn_short) > 1e-9:
                raw_sym_by_user[uid] = {
                    "mt5_long": mt5_long, "mt5_short": mt5_short,
                    "binance_long": bn_long, "binance_short": bn_short,
                    "mt5_symbols": sorted((mt5.get(uid, {}) or {}).keys()),
                    "binance_symbols": sorted((bn.get(uid, {}) or {}).keys()),
                }
                user_ids.add(uid)
    except Exception as e:
        logger.warning(f"[proc-monitor] raw position read failed: {e}")

    # ── Reconciliation ──────────────────────────────────────────────────
    def _has_pos(p: Dict[str, float]) -> Dict[str, bool]:
        if not p:
            return {"mt5": False, "binance": False}
        return {
            "mt5": abs(p.get("mt5_long", 0) or 0) > 1e-9 or abs(p.get("mt5_short", 0) or 0) > 1e-9,
            "binance": abs(p.get("binance_long", 0) or 0) > 1e-9 or abs(p.get("binance_short", 0) or 0) > 1e-9,
        }

    matrix: List[Dict[str, Any]] = []

    # (1) Process/active-key cells — authoritative per-pair, flags incl. live single-leg.
    for (uid, pair), cell in cells.items():
        pos = (pos_by_user_pair.get(uid, {}) or {}).get(pair)
        cell["positions"] = pos
        hp = _has_pos(pos)
        has_proc = any(p["liveness"] in ("running", "silent", "zombie") for p in cell["processes"])
        has_active_key = len(cell["active_keys"]) > 0
        flags: List[str] = []
        if any(p["liveness"] == "zombie" for p in cell["processes"]):
            flags.append("zombie")
        if any(p["liveness"] == "silent" for p in cell["processes"]):
            flags.append("silent")
        if hp["mt5"] != hp["binance"]:           # 进程在跑→单腿是真异常
            flags.append("single_leg")
        if has_active_key and not has_proc:
            flags.append("active_key_orphan")
        if has_proc and not has_active_key:
            flags.append("missing_active_key")
        cell["reconcile_flags"] = flags
        cell["healthy"] = (len(flags) == 0)
        cell["severity"] = ("critical" if any(f in ("single_leg", "zombie") for f in flags)
                            else ("warn" if flags else "ok"))
        cell["kind"] = "process"
        matrix.append(cell)

    # (2) Resting inventory — ONE row per user (net per-symbol exposure, no pair fan-out).
    #     Surfaces weekend/stopped open positions with no process watching them.
    for uid, agg in raw_sym_by_user.items():
        # skip users already shown with an engaged process holding positions
        if any(c["user_id"] == uid and c["processes"] for c in matrix):
            # still surface as inventory if engaged cells don't cover it, but avoid double-count noise
            pass
        hp = _has_pos(agg)
        # net direction balance check (lots vs contracts differ by conversion; use sign presence)
        imbalanced = hp["mt5"] != hp["binance"]
        flags = ["naked_position"]
        if imbalanced:
            flags.append("inventory_imbalance")
        matrix.append({
            "user_id": uid,
            "pair_code": "(库存)",
            "kind": "inventory",
            "processes": [],
            "active_keys": active_by_user.get(uid, []),
            "positions": {k: agg[k] for k in ("mt5_long", "mt5_short", "binance_long", "binance_short")},
            "symbols": {"mt5": agg.get("mt5_symbols", []), "binance": agg.get("binance_symbols", [])},
            "reconcile_flags": flags,
            "healthy": False,
            "severity": ("warn" if not imbalanced else "critical"),
        })

    # ── User roster (names) ─────────────────────────────────────────────
    users_out: List[Dict[str, Any]] = []
    # 仅用合法 UUID 查名(executor user_id 恒为 UUID;防御性过滤,避免脏键触发 UUID 解析 500)
    import uuid as _uuid
    def _is_uuid(v):
        try:
            _uuid.UUID(str(v)); return True
        except Exception:
            return False
    valid_uids = [u for u in user_ids if _is_uuid(u)]
    name_by_id = {}
    if valid_uids:
        try:
            rows = (await db.execute(
                select(User.user_id, User.username).where(User.user_id.in_(valid_uids))
            )).all()
            name_by_id = {str(r[0]): r[1] for r in rows}
        except Exception as e:
            logger.warning(f"[proc-monitor] username lookup failed: {e}")
            name_by_id = {}
    for uid in user_ids:
        u_cells = [c for c in matrix if c["user_id"] == uid]
        users_out.append({
            "user_id": uid,
            "username": name_by_id.get(str(uid), uid[:8] if uid else "?"),
            "process_count": sum(len(c["processes"]) for c in u_cells),
            "abnormal_count": sum(1 for c in u_cells if not c.get("healthy", True)),
            "has_inventory": any(c.get("kind") == "inventory" for c in u_cells),
            "pairs": sorted({c["pair_code"] for c in u_cells
                             if c["pair_code"] and c.get("kind") == "process"}),
        })

    # ── Global summary ──────────────────────────────────────────────────
    abnormal_cells = [c for c in matrix if not c.get("healthy", True)]
    summary = {
        "trading_users": len(users_out),
        "active_pairs": len({c["pair_code"] for c in matrix
                             if c.get("kind") == "process" and c["pair_code"]}),
        "running_processes": sum(1 for p in procs if p["liveness"] == "running"),
        "abnormal_processes": sum(1 for p in procs if p["liveness"] in ("zombie", "silent")),
        "inventory_users": sum(1 for c in matrix if c.get("kind") == "inventory"),
        "abnormal_cells": len(abnormal_cells),
        "total_processes": len(procs),
    }

    return {
        "summary": summary,
        "users": sorted(users_out, key=lambda u: (-u["abnormal_count"], u["username"])),
        "matrix": sorted(matrix, key=lambda c: (not c.get("healthy", True),
                                                c["user_id"], c["pair_code"]), reverse=True),
        "processes": procs,
        "ts": int(_time.time()),
    }


# ── P3: reconciliation alerter — panel red cells ⇆ Feishu/WS alerts, ONE source ──
# Critical flags from the SAME compute_process_snapshot() are emitted through the unified
# AlertBus with cooldown. single_leg reuses the existing "single_leg_alert" template_key so
# it dedups against the executor's own single-leg alert (no double-fire); zombie / naked use
# their own keys. owner_user_id routes to that trader's Feishu + admin fan-out.
async def run_reconciliation_alert_scan(db) -> int:
    """Scan the process snapshot and emit cooldown-gated alerts for critical reconcile
    flags. Returns number of alerts emitted (post-cooldown). Best-effort; never raises."""
    emitted = 0
    try:
        from app.services.agent.feishu_broadcast import broadcast
    except Exception as e:
        logger.warning(f"[proc-monitor] alert import failed: {e}")
        return 0
    try:
        snap = await compute_process_snapshot(db)
    except Exception as e:
        logger.warning(f"[proc-monitor] snapshot for alert failed: {e}")
        return 0

    FLAG_META = {
        "zombie":     ("danger", "strategy_zombie",  "策略进程僵尸(心跳停滞,看门狗将清)"),
        "single_leg": ("danger", "single_leg_alert", "单腿暴露(对冲腿缺失)"),
    }
    # 仅对 CRITICAL 标志告警(僵尸/单腿=管理员需立即处理);naked_position / inventory_imbalance
    # 是面板可见的留存库存提示,不发飞书(休市留仓普遍,避免刷屏)。面板与告警仍同源:都来自
    # compute_process_snapshot 的 reconcile_flags,只是告警侧只取需要行动的子集。
    for cell in snap.get("matrix", []):
        flags = cell.get("reconcile_flags") or []
        uid = cell.get("user_id") or ""
        pair = cell.get("pair_code") or ""
        for f in flags:
            if f not in FLAG_META:
                continue
            level, tkey, label = FLAG_META[f]
            msg = (f"🔧 策略对账告警 · {label}\n"
                   f"用户: {uid[:8]} | 产品对: {pair}\n"
                   f"标志: {', '.join(flags)}")
            try:
                rid = await broadcast(
                    db, level=level, category=tkey, message=msg,
                    owner_user_id=uid or None, pair_code=pair,
                    cooldown_s=1800,  # 30min,与健康监控一致
                    payload={"reconcile_flags": flags, "pair_code": pair},
                )
                if rid:
                    emitted += 1
            except Exception as _e:
                logger.debug(f"[proc-monitor] reconcile alert emit failed ({f}): {_e}")
    if emitted:
        logger.info(f"[proc-monitor] reconciliation emitted {emitted} alert(s)")
    return emitted
