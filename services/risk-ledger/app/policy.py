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


# 账户限制信号分类(V5 §6.3/ADR-008)——HARD=账户级权限/风控/冻结(→NO_NEW),TRANSPORT=网络限频(不判封号)。
_HARD_CODES = ("-2015", "-1002", "-2008", "10003", "10004", "10005", "33004", "50111", "50113",
               "40001", "40009", "40012", "401", "403")
_HARD_WORDS = ("permission", "unauthorized", "forbidden", "banned", "restrict", "kyc", "frozen",
               "invalid api", "api-key", "ip ", "not allowed", "suspend")
_TRANSPORT_WORDS = ("timeout", "timed out", "connect", "ssl", "temporarily", "read error", "429",
                    "too many", "-1003", "gateway", "503", "502")


def classify_err(err: str):
    """(severity, signal_type)。HARD→账户限制(NO_NEW);TRANSPORT→网络(不下压模式,WATCH 已够);MEDIUM 其余。"""
    e = (err or "").lower()
    if any(w in e for w in _TRANSPORT_WORDS) or any(c in e for c in ("-1003", "429", "503", "502")):
        return "TRANSPORT", "NETWORK"
    if any(c in e for c in _HARD_CODES) or any(w in e for w in _HARD_WORDS):
        return "HARD", "PERMISSION_OR_RISK"
    return "MEDIUM", "PRIVATE_API_ERROR"


async def _venue_exposure(r, venue: str):
    """从 dcm:account:{venue} 算在场名义 = Σ|qty|×mark;返回 (notional, equity, ok, err)。"""
    try:
        a = json.loads(await r.get(f"dcm:account:{venue}") or "{}")
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, False, "snapshot缺失"
    if not a.get("ok"):
        return 0.0, float(a.get("equity_usdt") or 0), False, str(a.get("err") or "")
    positions = a.get("positions") or {}
    detail = a.get("pos_detail") or {}
    notional = 0.0
    for sym, qty in positions.items():
        mark = float((detail.get(sym) or {}).get("mark") or 0)
        notional += abs(float(qty or 0)) * mark
    return notional, float(a.get("equity_usdt") or 0), True, ""


async def _persist_restriction(pool, venue, severity, signal_type, err):
    """落 restriction_event(dedup by venue+code,ON CONFLICT 累加 hit_count/更新 last_seen)。"""
    if pool is None:
        return
    dedupe = f"{venue}:{signal_type}:{(err or '')[:40]}"
    try:
        await pool.execute(
            "INSERT INTO restriction_event(venue,scope,signal_type,source_type,severity,raw_code,"
            "raw_payload,dedupe_key) VALUES($1,'VENUE',$2,'ACCOUNT_FACT',$3,$4,$5,$6) "
            "ON CONFLICT (dedupe_key) DO UPDATE SET last_seen=now(), hit_count=restriction_event.hit_count+1",
            venue, signal_type, severity, (err or "")[:40], (err or "")[:500], dedupe)
    except Exception:  # noqa: BLE001
        pass


import os as _os

COREBOX_DROP_USDT = float(_os.environ.get("DCM_COREBOX_DROP_USDT", "2000"))   # 单区间净流出绝对阈
COREBOX_DROP_PCT = float(_os.environ.get("DCM_COREBOX_DROP_PCT", "0.02"))      # 单区间净流出比例阈


async def corebox_check(r, fire=None) -> dict:
    """CORE_POOL 封闭盒子不变量:读 dcm:risk:corebox 组总权益,对比上区间基线。
    突降 > max(绝对阈, 比例阈)=可能净流出/强平/盒子被破 → P0 告警(delta 中性组不该单区间大跌)。
    成员账户快照失败(ok=false)=可能被风控/限制 → 告警。基线存 Redis(重启不丢)。只读只告警。"""
    try:
        cb = json.loads(await r.get("dcm:risk:corebox") or "{}")
    except Exception:  # noqa: BLE001
        return {"ok": False, "note": "corebox 未发布"}
    members = cb.get("members") or []
    if not members:
        return {"ok": True, "note": "CORE_POOL 组为空(未入金)", "member_count": 0}
    total = float(cb.get("total_equity_usdt") or 0)
    try:
        base = json.loads(await r.get("dcm:risk:corebox:baseline") or "{}")
    except Exception:  # noqa: BLE001
        base = {}
    last = float(base.get("equity_usdt")) if base.get("equity_usdt") is not None else None

    alerts = []
    # ① 突降 = 净流出/强平嫌疑
    if last is not None and total < last:
        drop = last - total
        thr = max(COREBOX_DROP_USDT, COREBOX_DROP_PCT * last)
        if drop > thr:
            alerts.append(("corebox-drop",
                           f"CORE_POOL 组权益突降 {drop:.0f}U({last:.0f}→{total:.0f},阈{thr:.0f})"
                           f"——delta 中性组不该单区间大跌,查是否净流出/强平/单腿爆", "fatal"))
    # ② 成员账户快照失败 = 可能账户限制/封号
    for m in members:
        if not m.get("ok") and m.get("has_key"):
            alerts.append((f"corebox-member:{m['account_key']}",
                           f"CORE_POOL 成员 {m.get('name')} 账户快照失败(可能被限制/封号/网络)", "warn"))
    if fire:
        for key, msg, lvl in alerts:
            await fire(key, "CORE_POOL 封闭盒子告警", msg, level=lvl)

    # 更新基线(记录当前;上升或小幅波动都刷新,只对突降告警)
    await r.set("dcm:risk:corebox:baseline",
                json.dumps({"equity_usdt": total, "ts": int(time.time()),
                            "member_count": len(members)}), ex=86400)
    mon = {"ts": int(time.time()), "total_equity_usdt": total, "prev_equity_usdt": last,
           "member_count": len(members), "alerts": [a[0] for a in alerts],
           "sealed": len(alerts) == 0}
    await r.set("dcm:risk:corebox:monitor", json.dumps(mon, ensure_ascii=False), ex=180)
    return mon


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
        notional, equity, ok, err = await _venue_exposure(r, v)
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
            # 账户快照失败→分类:HARD 权限/风控/冻结=账户限制→NO_NEW(自动保命反射);
            # TRANSPORT 网络限频=不判封号只 WATCH;落 restriction_event 供追溯。
            severity, sig = classify_err(err)
            auto_mode = "NO_NEW_RISK" if severity == "HARD" else "WATCH"
            mode = _stricter(mode, auto_mode)
            reason = f"账户失败[{severity}:{err[:50]}]|" + reason
            await _persist_restriction(pool, v, severity, sig, err)
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

    # (epoch, sequence) 双单调 fencing(ADR-005):消费者按字典序只接受更高。
    # DB 恢复/权威重建 → 手动 bump epoch(避免 sequence 回退使旧快照复活);sequence 每轮 +1。
    epoch, version = 1, int(time.time())
    if pool is not None:
        try:
            row = await pool.fetchrow(
                "UPDATE risk_policy_version SET policy_version = policy_version + 1, updated_at = now() "
                "WHERE id = 1 RETURNING policy_epoch, policy_version")
            if row:
                epoch, version = int(row["policy_epoch"]), int(row["policy_version"])
        except Exception:  # noqa: BLE001
            pass

    summary = {
        "policy_epoch": epoch, "policy_version": version, "ts": int(time.time()),
        "global_mode": global_ovr,
        "venues": venues_out,
        "capped_venues": [v for v, d in venues_out.items() if d["mode"] != "NORMAL"],
    }
    await r.set(POLICY_KEY, json.dumps(summary, ensure_ascii=False), ex=180)
    return summary
