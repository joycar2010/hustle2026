"""G0 风险策略权威计算与发布(V5 补充说明 ADR-001/002/003)——risk-ledger 唯一计算/发布者。

每轮:读 risk_venue_cap 上限 + 最新未过期 risk_policy_override + dcm:account 实时敞口
     → 逐 scope 计算有效模式(max 严格度)+ 动作能力位 → 单调版本号 → 发布 dcm:risk:policy。
消费者(opener/manager/exec-kernel)只接受更高 policy_version(防旧快照复活,G0 fencing 雏形)。

铁律(risk-ledger 同款):只计算发布,绝不下单;敞口只读 dcm:account 快照。
模式严格度序:NORMAL < WATCH < NO_NEW_RISK < REDUCE_ONLY < EXIT_ONLY < FROZEN。
"""
import json
import time

MODES = ["NORMAL", "WATCH", "NO_NEW_RISK", "REDUCE_ONLY", "EXIT_ONLY", "FROZEN"]
_RANK = {m: i for i, m in enumerate(MODES)}
SUPPORTED_VENUES = ("binance", "bybit", "okx", "gate", "bitget", "hyperliquid")

POLICY_KEY = "dcm:risk:policy"


def _stricter(a: str, b: str) -> str:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def _capabilities(mode: str) -> dict:
    """动作能力位(ADR-003):不只 mode 枚举,明确逐动作。减险类永远允许,增险类按 mode 收紧。"""
    rank = _RANK.get(mode, 0)
    can_open = rank <= _RANK["WATCH"]          # 仅 NORMAL/WATCH 可新增
    not_frozen = rank < _RANK["FROZEN"]
    return {
        "CAN_QUERY": True,
        "CAN_CANCEL": not_frozen,
        "CAN_OPEN": can_open,
        "CAN_INCREASE_GROSS": can_open,
        "CAN_INCREASE_DEBT": can_open,
        "CAN_REDUCE": not_frozen,
        "CAN_REPAY": not_frozen,
        "CAN_RESCUE_HEDGE": rank <= _RANK["REDUCE_ONLY"],  # EXIT_ONLY/FROZEN 不再新建救援腿
        "CAN_COMPLETE_HEDGE": not_frozen,                  # 补对冲=减险,允许到 EXIT_ONLY
    }


async def _venue_exposure(r, venue: str):
    """从 dcm:account:{venue} 算在场名义 = Σ|qty|×mark;返回 (notional, equity, ok)。"""
    try:
        a = json.loads(await r.get(f"dcm:account:{venue}") or "{}")
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, False
    if not a.get("ok"):
        return 0.0, float(a.get("equity_usdt") or 0), False
    positions = a.get("positions") or {}
    detail = a.get("pos_detail") or {}
    notional = 0.0
    for sym, qty in positions.items():
        mark = float((detail.get(sym) or {}).get("mark") or 0)
        notional += abs(float(qty or 0)) * mark
    return notional, float(a.get("equity_usdt") or 0), True


async def compute_and_publish(pool, r) -> dict:
    """计算有效策略并发布。pool=dcm_main(读 cap/override,写 version);r=Redis。返回 summary。"""
    caps, overrides = {}, {}
    if pool is not None:
        try:
            for row in await pool.fetch("SELECT scope_key, tier, max_notional_usdt, warn_ratio, enabled "
                                        "FROM risk_venue_cap WHERE enabled = TRUE"):
                caps[row["scope_key"]] = dict(row)
        except Exception:  # noqa: BLE001  # 表未建/无权限时降级为无上限(不 fail-closed 发布,静默)
            pass
        try:
            # 每 scope 取最新未过期 override
            for row in await pool.fetch(
                    "SELECT DISTINCT ON (scope_type, scope_key) scope_type, scope_key, mode, reason, expires_at "
                    "FROM risk_policy_override "
                    "WHERE expires_at IS NULL OR expires_at > now() "
                    "ORDER BY scope_type, scope_key, id DESC"):
                overrides[f"{row['scope_type']}:{row['scope_key']}"] = dict(row)
        except Exception:  # noqa: BLE001
            pass

    global_ovr = overrides.get("GLOBAL:GLOBAL", {}).get("mode", "NORMAL")
    venues_out = {}
    for v in SUPPORTED_VENUES:
        notional, equity, ok = await _venue_exposure(r, v)
        cap_row = caps.get(f"venue:{v}")
        mode, reason = "NORMAL", "ok"
        cap_val = float(cap_row["max_notional_usdt"]) if cap_row else None
        warn_ratio = float(cap_row["warn_ratio"]) if cap_row else 0.85
        if cap_val is not None:
            if notional >= cap_val:
                mode, reason = "NO_NEW_RISK", f"敞口{notional:.0f}≥上限{cap_val:.0f}U"
            elif notional >= cap_val * warn_ratio:
                mode, reason = "WATCH", f"敞口{notional:.0f}≥{warn_ratio:.0%}上限"
        if not ok:
            mode, reason = _stricter(mode, "WATCH"), reason + "|账户快照失败"
        # 合并 override(venue 级 + 全局,取最严格)
        vovr = overrides.get(f"VENUE:{v}", {}).get("mode")
        if vovr:
            mode = _stricter(mode, vovr)
            reason = f"override={vovr};{reason}"
        mode = _stricter(mode, global_ovr)
        venues_out[v] = {
            "mode": mode, "reason": reason,
            "exposure_notional": round(notional, 2), "equity": round(equity, 2),
            "cap_usdt": cap_val, "warn_ratio": warn_ratio,
            "capabilities": _capabilities(mode),
        }

    # 单调版本号(消费者只接受更高版本;DB 权威,重启不回退)
    version = int(time.time())
    if pool is not None:
        try:
            row = await pool.fetchrow(
                "UPDATE risk_policy_version SET policy_version = policy_version + 1, updated_at = now() "
                "WHERE id = 1 RETURNING policy_version")
            if row:
                version = int(row["policy_version"])
        except Exception:  # noqa: BLE001
            pass

    summary = {
        "policy_version": version, "ts": int(time.time()),
        "global_mode": global_ovr,
        "venues": venues_out,
        "capped_venues": [v for v, d in venues_out.items() if d["mode"] != "NORMAL"],
    }
    await r.set(POLICY_KEY, json.dumps(summary, ensure_ascii=False), ex=180)
    return summary
