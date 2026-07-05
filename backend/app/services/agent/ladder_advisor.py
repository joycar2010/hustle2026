"""OpenCLAW → testgo 阶梯自动调参层(影子对比 → 分级自动应用)。

定位: 不碰下单热路径(testgo continuous_executor 原样执行), 只做慢变量调参 —
按小时评估各 target(user×strategy_type×pair) 的阶梯参数是否贴合近期点差分布,
LLM 产出 new_ladders 提案, 按 ladder_advisor_config.mode 分级处置:
  shadow     只落 ladder_advisor_log(不动配置不通知) — 观察期默认
  suggest    落库 + 飞书通知人工(不自动改)
  auto_small 幅度≤max_auto_pct 且通过硬校验 → 直接 UPDATE strategy_configs.ladders
             (testgo 运行中策略 3s 热重载生效), 超幅度降级为 suggest
  auto       同上但不设幅度上限(仍受30%硬上限)
硬校验(独立于LLM, 铁律):
  - 阶梯数不变, 每阶只允许改 openPrice/threshold/qtyLimit
  - qtyLimit 总量不得增加(防LLM加仓)
  - openPrice/threshold 单阶变幅硬上限30%
  - openPrice-threshold 利润间距 >= 0.3
  - 冷却: 同 target cooldown_hours 内只动一次
回滚: ladder_advisor_log.old_ladders 存快照。
影子对比: 每条提案记 pnl_before_7d; 24h 后回填 pnl_after_24h。
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.agent.codex_client import call_decider
from app.services.agent.feishu_broadcast import broadcast

logger = logging.getLogger(__name__)

WAKE_INTERVAL_S = 3600           # 每小时评估一次
OUTCOME_BACKFILL_S = 1800        # 每30min回填 pnl_after_24h
_task: Optional[asyncio.Task] = None
_outcome_task: Optional[asyncio.Task] = None

ADVISOR_SYSTEM_PROMPT = (
    "你是黄金/白银跨所对冲阶梯套利的调参器(不下单, 只调参数)。\n"
    "给定某 target 的当前阶梯配置和近24h点差分布统计, 判断阶梯是否贴合行情:\n"
    "- 若点差分布整体漂移(均值/中位数移动), 各阶 openPrice 可平移贴近可成交区\n"
    "- 若波动收窄, 远端 openPrice 长期够不到 → 可下调贴近 p90\n"
    "- 若波动放大, 可适度外推防止过早满仓\n"
    "- threshold(平仓价)与 openPrice 的间距=单笔毛利, 不得压缩到 <0.3\n"
    "- 禁止增加任何 qtyLimit; 禁止增减阶梯数; 禁止翻转 enabled\n"
    "输出严格 JSON(无额外文字):\n"
    '{"action":"propose"|"no_change","rationale":"为什么/预期影响(<150字)",'
    '"new_ladders":[与输入同长度同字段的数组]}\n'
    "no_change 时 new_ladders 可为 null。"
)


async def _spread_stats(db, symbol: str, hours: int = 24) -> Optional[Dict[str, Any]]:
    r = (await db.execute(text("""
        SELECT count(*) n,
               round(avg(forward_spread)::numeric,3),
               round((percentile_cont(0.1) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
               round((percentile_cont(0.9) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
               round(avg(reverse_spread)::numeric,3),
               round((percentile_cont(0.1) WITHIN GROUP (ORDER BY reverse_spread))::numeric,3),
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY reverse_spread))::numeric,3),
               round((percentile_cont(0.9) WITHIN GROUP (ORDER BY reverse_spread))::numeric,3)
        FROM spread_records
        WHERE timestamp > (now() at time zone 'utc') - make_interval(hours=>:h)
          AND symbol = :sym
    """), {"h": hours, "sym": symbol})).first()
    if not r or not r[0]:
        return None
    return {
        "n": int(r[0]),
        "forward": {"avg": float(r[1]), "p10": float(r[2]), "p50": float(r[3]), "p90": float(r[4])},
        "reverse": {"avg": float(r[5]), "p10": float(r[6]), "p50": float(r[7]), "p90": float(r[8])},
    }


def _validate_diff(old: List[dict], new: List[dict], max_pct: Optional[float]) -> Optional[str]:
    """硬校验(独立于LLM)。返回 None=通过, 否则违规原因。"""
    if not isinstance(new, list) or len(new) != len(old):
        return "ladder_count_changed"
    total_old = sum(float(l.get("qtyLimit", 0)) for l in old)
    total_new = 0.0
    for i, (o, n) in enumerate(zip(old, new)):
        if set(n.keys()) - {"enabled", "qtyLimit", "openPrice", "threshold"}:
            return f"ladder{i}_unknown_keys"
        if bool(n.get("enabled", True)) != bool(o.get("enabled", True)):
            return f"ladder{i}_enabled_flip_forbidden"
        try:
            n_op, o_op = float(n["openPrice"]), float(o["openPrice"])
            n_th, o_th = float(n["threshold"]), float(o["threshold"])
            n_q = float(n.get("qtyLimit", 0))
        except Exception:
            return f"ladder{i}_bad_types"
        total_new += n_q
        for name, nv, ov in (("openPrice", n_op, o_op), ("threshold", n_th, o_th)):
            base = max(abs(ov), 0.5)  # 原值近0时用0.5做分母防误杀
            pct = abs(nv - ov) / base * 100
            cap = min(30.0, max_pct) if max_pct is not None else 30.0
            if pct > cap:
                return f"ladder{i}_{name}_change_{pct:.0f}pct_gt_{cap:.0f}"
        if n_op - n_th < 0.3:
            return f"ladder{i}_profit_gap_lt_0.3"
    if total_new > total_old + 1e-9:
        return "qty_total_increase"
    return None


async def _pnl_window(db, user_id: str, start_sql: str, end_sql: str, params: dict) -> float:
    """通用: [start,end) 窗口内该用户 binance income(非TRANSFER)+mt5平仓 的合计。"""
    q = f"""
        SELECT COALESCE((SELECT sum(bi.income) FROM binance_income bi
                JOIN accounts a ON bi.account_id=a.account_id
                WHERE a.user_id=CAST(:u AS UUID) AND bi.income_type<>'TRANSFER'
                  AND bi.income_time_ms >= {start_sql} AND bi.income_time_ms < {end_sql}),0)
             + COALESCE((SELECT sum(m.profit+m.swap+m.commission) FROM mt5_deals m
                JOIN accounts a ON m.account_id=a.account_id
                WHERE a.user_id=CAST(:u AS UUID) AND m.entry=1 AND m.symbol<>''
                  AND (extract(epoch from m.deal_time_utc)*1000) >= {start_sql}
                  AND (extract(epoch from m.deal_time_utc)*1000) < {end_sql}),0)
    """
    r = (await db.execute(text(q), {"u": str(user_id), **params})).scalar()
    return float(r or 0)


async def _evaluate_target(db, cfg_row, advisor_cfg) -> None:
    user_id, strategy_type, pair_code, ladders, symbol = cfg_row
    old = ladders if isinstance(ladders, list) else json.loads(ladders)
    if not old:
        return
    stats = await _spread_stats(db, symbol or "XAUUSDT")
    if not stats or stats["n"] < 1000:
        return  # 点差样本不足不提案
    cool = (await db.execute(text("""
        SELECT count(*) FROM ladder_advisor_log
        WHERE user_id=CAST(:u AS UUID) AND strategy_type=:st AND pair_code=:pc
          AND action IN ('applied','suggested')
          AND created_at > now() - make_interval(hours=>:ch)
    """), {"u": str(user_id), "st": strategy_type, "pc": pair_code,
           "ch": int(advisor_cfg["cooldown_hours"])})).scalar()
    if cool:
        return
    side = "reverse" if "reverse" in strategy_type else "forward"
    user_prompt = json.dumps({
        "strategy_type": strategy_type, "pair_code": pair_code,
        "current_ladders": old, "spread_stats_24h": stats[side],
        "note": f"{side}方向; openPrice=开仓触发点差, threshold=平仓点差",
    }, ensure_ascii=False)
    try:
        # call_decider 返回 (proposal_dict|None, token_usage, latency_ms); 熔断开时返回 noop dict
        prop, _tok, _lat = await call_decider(ADVISOR_SYSTEM_PROMPT, user_prompt, db=db)
        if not isinstance(prop, dict):
            return
        if prop.get("action") == "noop":   # 熔断/降级 → 本轮跳过
            return
    except Exception as e:
        logger.warning(f"[ladder_advisor] LLM decide failed {pair_code}/{strategy_type}: {e}")
        return
    if prop.get("action") != "propose" or not prop.get("new_ladders"):
        return
    new = prop["new_ladders"]
    mode = advisor_cfg["mode"]
    max_pct = float(advisor_cfg["max_auto_pct"]) if mode == "auto_small" else None
    violation = _validate_diff(old, new, max_pct)
    pnl7 = await _pnl_window(
        db, user_id,
        "(extract(epoch from now())-7*86400)*1000", "extract(epoch from now())*1000", {})

    action = "shadow"
    if mode in ("auto_small", "auto") and violation is None:
        action = "applied"
    elif mode in ("suggest", "auto_small", "auto"):
        action = "suggested"   # auto但违规→降级为建议

    if action == "applied":
        await db.execute(text("""
            UPDATE strategy_configs
            SET ladders=CAST(:l AS JSONB), update_time=now() at time zone 'utc'
            WHERE user_id=CAST(:u AS UUID) AND strategy_type=:st AND pair_code=:pc
        """), {"l": json.dumps(new), "u": str(user_id), "st": strategy_type, "pc": pair_code})
    await db.execute(text("""
        INSERT INTO ladder_advisor_log(user_id, strategy_type, pair_code, mode, action,
            old_ladders, new_ladders, rationale, spread_stats, pnl_before_7d)
        VALUES (CAST(:u AS UUID), :st, :pc, :mode, :act, CAST(:old AS JSONB), CAST(:new AS JSONB),
                :rat, CAST(:stats AS JSONB), :p7)
    """), {"u": str(user_id), "st": strategy_type, "pc": pair_code, "mode": mode, "act": action,
           "old": json.dumps(old), "new": json.dumps(new),
           "rat": ((prop.get("rationale") or "")[:1000]
                   + (f" [硬校验拦截:{violation}]" if violation else "")),
           "stats": json.dumps(stats), "p7": pnl7})
    await db.commit()
    if action in ("applied", "suggested"):
        try:
            await broadcast(
                db,
                level="warning" if action == "applied" else "info",
                category="ladder_advisor",
                message=(f"[阶梯调参:{action}] {pair_code}/{strategy_type} — "
                         + (prop.get("rationale") or "")[:280]
                         + (f" (违规降级:{violation})" if violation else "")),
                pair_code=pair_code,
                owner_user_id=str(user_id),
            )
        except Exception:
            pass
    logger.info(f"[ladder_advisor] {pair_code}/{strategy_type} action={action} violation={violation}")


async def _loop():
    await asyncio.sleep(120)  # 起服延迟, 避开启动高峰
    while True:
        try:
            async with AsyncSessionLocal() as db:
                adv = (await db.execute(text(
                    "SELECT mode, max_auto_pct, cooldown_hours, enabled "
                    "FROM ladder_advisor_config WHERE id=1"))).first()
                if adv and adv[3]:
                    advisor_cfg = {"mode": adv[0], "max_auto_pct": adv[1], "cooldown_hours": adv[2]}
                    # 联动 /risk(20260704): kill_switch=紧急停机 → 暂停一切提案(含shadow)
                    _ks = (await db.execute(text(
                        "SELECT kill_switch FROM agent_state WHERE id=1"))).scalar()
                    if _ks:
                        logger.info("[ladder_advisor] paused by kill_switch")
                        await asyncio.sleep(WAKE_INTERVAL_S)
                        continue
                    # 联动作用域: agent_scope_targets 有 enabled 行时, 只评估其 (user,pair) 交集
                    _scope = {(str(r[0]), r[1]) for r in (await db.execute(text(
                        "SELECT user_id, pair_code FROM agent_scope_targets WHERE enabled"))).all()}
                    rows = (await db.execute(text("""
                        SELECT sc.user_id, sc.strategy_type, sc.pair_code, sc.ladders,
                               (SELECT ps.symbol FROM hedging_pairs hp
                                JOIN platform_symbols ps ON hp.symbol_a_id=ps.id
                                WHERE hp.pair_code=sc.pair_code LIMIT 1) AS symbol
                        FROM strategy_configs sc
                        WHERE sc.ladders::text <> '[]'
                    """))).all()
                    for row in rows:
                        if _scope and (str(row[0]), row[2]) not in _scope:
                            continue  # 作用域启用时只评估选中的用户×产品对
                        try:
                            await _evaluate_target(db, row, advisor_cfg)
                        except Exception as e:
                            logger.warning(f"[ladder_advisor] target eval failed: {e}")
        except Exception as e:
            logger.error(f"[ladder_advisor] loop error: {e}")
        await asyncio.sleep(WAKE_INTERVAL_S)


async def _outcome_loop():
    """回填提案 24h 后的实际收益(影子对比核心数据)。"""
    await asyncio.sleep(300)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(text("""
                    SELECT id, user_id FROM ladder_advisor_log
                    WHERE outcome_at IS NULL AND created_at < now() - interval '24 hours'
                    LIMIT 20
                """))).all()
                for log_id, uid in rows:
                    pnl = await _pnl_window(
                        db, uid,
                        "(SELECT extract(epoch from l.created_at)*1000 FROM ladder_advisor_log l WHERE l.id=:lid)",
                        "(SELECT (extract(epoch from l.created_at)+86400)*1000 FROM ladder_advisor_log l WHERE l.id=:lid)",
                        {"lid": log_id})
                    await db.execute(text(
                        "UPDATE ladder_advisor_log SET pnl_after_24h=:p, outcome_at=now() WHERE id=:lid"),
                        {"p": pnl, "lid": log_id})
                await db.commit()
        except Exception as e:
            logger.error(f"[ladder_advisor] outcome loop error: {e}")
        await asyncio.sleep(OUTCOME_BACKFILL_S)


def start():
    global _task, _outcome_task
    if os.getenv("LADDER_ADVISOR_ENABLED", "0").lower() not in ("1", "true", "on"):
        logger.info("[ladder_advisor] disabled by env")
        return
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop())
    _outcome_task = loop.create_task(_outcome_loop())
    logger.info("[ladder_advisor] started (mode from ladder_advisor_config)")


async def stop():
    for t in (_task, _outcome_task):
        if t:
            t.cancel()
