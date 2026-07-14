"""G0 风险策略权威计算与发布(V5 补充说明 ADR-001/002/003)——risk-ledger 唯一计算/发布者。

每轮:读 risk_venue_cap 上限 + 最新未过期 risk_policy_override + dcm:account 实时敞口
     → 逐 scope 计算有效模式(max 严格度)+ 动作能力位 → 单调版本号 → 发布 dcm:risk:policy。
消费者(opener/manager/exec-kernel)只接受更高 policy_version(防旧快照复活,G0 fencing 雏形)。

铁律(risk-ledger 同款):只计算发布,绝不下单;敞口只读 dcm:account 快照。
模式严格度序:NORMAL < WATCH < NO_NEW_RISK < REDUCE_ONLY < EXIT_ONLY < FROZEN。
"""
import json
import os as _os
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
    """从 dcm:account:{venue} 算在场名义 = Σ|qty|×mark;返回 (notional, equity, ok, err, key_fp)。"""
    try:
        a = json.loads(await r.get(f"dcm:account:{venue}") or "{}")
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, False, "snapshot缺失", ""
    fp = str(a.get("key_fp") or "")
    if not a.get("ok"):
        return 0.0, float(a.get("equity_usdt") or 0), False, str(a.get("err") or ""), fp
    positions = a.get("positions") or {}
    detail = a.get("pos_detail") or {}
    notional = 0.0
    for sym, qty in positions.items():
        mark = float((detail.get(sym) or {}).get("mark") or 0)
        notional += abs(float(qty or 0)) * mark
    return notional, float(a.get("equity_usdt") or 0), True, "", fp


async def _credential_epoch(pool, venue: str, key_fp: str):
    """凭证代次(ADR-005):key 指纹变化=轮换→epoch+1。返回 (epoch, rotated)。"""
    if pool is None or not key_fp:
        return None, False
    try:
        row = await pool.fetchrow("SELECT epoch, key_fingerprint FROM credential_epoch WHERE venue=$1", venue)
        if row is None:
            await pool.execute("INSERT INTO credential_epoch(venue, epoch, key_fingerprint) "
                               "VALUES($1, 1, $2) ON CONFLICT (venue) DO NOTHING", venue, key_fp)
            return 1, False
        if row["key_fingerprint"] and row["key_fingerprint"] != key_fp:
            await pool.execute("UPDATE credential_epoch SET epoch=epoch+1, key_fingerprint=$2, "
                               "updated_at=now(), note='auto: key指纹变化' WHERE venue=$1", venue, key_fp)
            return int(row["epoch"]) + 1, True
        if not row["key_fingerprint"]:
            await pool.execute("UPDATE credential_epoch SET key_fingerprint=$2, updated_at=now() "
                               "WHERE venue=$1", venue, key_fp)
        return int(row["epoch"]), False
    except Exception:  # noqa: BLE001  # 表未建/迁移中:不阻塞策略发布
        return None, False


# WithdrawalSentinel 提现延迟阈(V5 §7.2;提现罕见无 p95 基线时用绝对阈,crypto 正常分钟~1h 完成)
WD_WATCH_SEC = int(_os.environ.get("DCM_WD_WATCH_SEC", "21600"))       # pending>6h → WATCH
WD_REDUCE_SEC = int(_os.environ.get("DCM_WD_REDUCE_SEC", "86400"))     # pending>24h → REDUCE_ONLY
WD_FAIL_NONEW = int(_os.environ.get("DCM_WD_FAIL_NONEW", "2"))         # 连败≥2 → NO_NEW


async def _withdrawal_mode(r, venue):
    """读 dcm:risk:withdrawal:{venue} → (mode, reason)。提现延迟/连败=平台交易对手风险(V5 §7.2)。
    有 p95 基线则用 max(绝对阈, 2×p95);无基线用绝对阈。无数据=NORMAL。"""
    try:
        wh = json.loads(await r.get(f"dcm:risk:withdrawal:{venue}") or "{}")
    except Exception:  # noqa: BLE001
        return "NORMAL", ""
    if not wh:
        return "NORMAL", ""
    age = float(wh.get("oldest_pending_age_sec") or 0)
    p95 = float(wh.get("p95_sec") or 0)
    watch_thr = max(WD_WATCH_SEC, 2 * p95) if p95 else WD_WATCH_SEC
    reduce_thr = max(WD_REDUCE_SEC, 4 * p95) if p95 else WD_REDUCE_SEC
    if int(wh.get("recent_failures") or 0) >= WD_FAIL_NONEW:
        return "NO_NEW_RISK", f"提现连败{wh['recent_failures']}次(平台限制嫌疑)"
    if age > reduce_thr:
        return "REDUCE_ONLY", f"提现pending {int(age/3600)}h>{int(reduce_thr/3600)}h(严重延迟)"
    if age > watch_thr:
        return "WATCH", f"提现pending {int(age/3600)}h>{int(watch_thr/3600)}h(延迟)"
    return "NORMAL", ""


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


# trapped capital → NAV haircut(V4 §20/G2):受限 venue 的权益按模式折价——提不出来的钱不是完整的钱。
# 折价率 env 覆写:DCM_NAV_HAIRCUT="NO_NEW_RISK:0.1,REDUCE_ONLY:0.3,EXIT_ONLY:0.5,FROZEN:1"
_HAIRCUT_DEFAULT = {"NORMAL": 0.0, "WATCH": 0.0, "NO_NEW_RISK": 0.10,
                    "REDUCE_ONLY": 0.30, "EXIT_ONLY": 0.50, "FROZEN": 1.00}


def _haircuts() -> dict:
    hc = dict(_HAIRCUT_DEFAULT)
    for part in _os.environ.get("DCM_NAV_HAIRCUT", "").split(","):
        k, _, val = part.partition(":")
        if k.strip() in hc and val:
            try:
                hc[k.strip()] = min(1.0, max(0.0, float(val)))
            except ValueError:
                pass
    return hc


# RECOVERY_WATCH 恢复阶梯(V5 §7.3):REDUCE_ONLY+ 事件出清后不许直跳 NORMAL——
# 额度 10%→25%→50%→100%,每级驻留≥一个结算周期(默认8h)且该 venue 无活跃 fatal Incident;
# 操作员显式 override NORMAL(审计过的人工放行)可提前关闭恢复期。
RECOVERY_STAGE_SEC = int(_os.environ.get("DCM_RECOVERY_STAGE_SEC", "28800"))
_REC_PCT = (0.10, 0.25, 0.50, 1.00)
POLICY_UNCLEAR_MODE = _os.environ.get("DCM_POLICY_UNCLEAR_MODE", "WATCH")


async def _apply_recovery(pool, venue, mode, reason, notional, cap_val, ovr_norm, has_fatal_incident):
    """恢复阶梯。返回 (mode, reason, recovery|None)。REDUCE+ 期间只登记事件;
    出清后压 WATCH+阶梯额度帽;满 4 级或操作员显式 NORMAL 放行才回 NORMAL。"""
    if pool is None:
        return mode, reason, None
    try:
        row = await pool.fetchrow(
            "SELECT stage, extract(epoch from now()-last_advance_at) AS since "
            "FROM venue_recovery WHERE venue=$1 AND active", venue)
        if _RANK.get(mode, 0) >= _RANK["REDUCE_ONLY"]:
            if row is None:
                await pool.execute(
                    "INSERT INTO venue_recovery(venue, active, stage, episode_mode) VALUES($1, TRUE, 0, $2) "
                    "ON CONFLICT (venue) DO UPDATE SET active=TRUE, stage=0, episode_mode=$2, "
                    "entered_at=now(), last_advance_at=now(), closed_at=NULL", venue, mode)
            else:   # 事件仍在:阶梯归零,计时从最后一次受限轮起算
                await pool.execute("UPDATE venue_recovery SET stage=0, episode_mode=$2, "
                                   "last_advance_at=now() WHERE venue=$1", venue, mode)
            return mode, reason, None
        if row is None or _RANK.get(mode, 0) >= _RANK["NO_NEW_RISK"]:
            return mode, reason, None   # 无恢复期在途 / NO_NEW 事件未出清,不推进阶梯
        if ovr_norm:
            await pool.execute("UPDATE venue_recovery SET active=FALSE, closed_at=now() WHERE venue=$1", venue)
            return mode, f"恢复期由操作员override NORMAL放行|{reason}", None
        stage = int(row["stage"])
        if float(row["since"] or 0) >= RECOVERY_STAGE_SEC and not has_fatal_incident:
            stage += 1
            if stage >= 3:   # 完成 100% → 关闭恢复期
                await pool.execute("UPDATE venue_recovery SET active=FALSE, stage=3, closed_at=now() "
                                   "WHERE venue=$1", venue)
                return mode, reason, None
            await pool.execute("UPDATE venue_recovery SET stage=$2, last_advance_at=now() WHERE venue=$1",
                               venue, stage)
        pct = _REC_PCT[min(stage, 3)]
        rmode = _stricter(mode, "WATCH")
        rreason = f"RECOVERY_WATCH 阶段{stage} 额度{int(pct * 100)}%|{reason}"
        if cap_val is not None and notional >= cap_val * pct:
            rmode = _stricter(rmode, "NO_NEW_RISK")
            rreason = f"恢复期敞口{notional:.0f}≥阶梯帽{cap_val * pct:.0f}U|" + rreason
        return rmode, rreason, {"stage": stage, "allow_pct": pct}
    except Exception:  # noqa: BLE001  # 表未建:恢复阶梯静默降级(不阻塞策略)
        return mode, reason, None


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

    # 批次4/5 输入:条款登记(PROHIBITED→FROZEN/UNCLEAR→WATCH)+ 活跃 Incident(incident_state 分离)
    vpolicy, inc_active = {}, {}
    if pool is not None:
        try:
            for row in await pool.fetch(
                    "SELECT venue, arbitrage_status, reviewed_at, next_review_at FROM venue_policy"):
                vpolicy[row["venue"]] = dict(row)
        except Exception:  # noqa: BLE001
            pass
        try:
            for row in await pool.fetch(
                    "SELECT venue, state, severity FROM venue_incident WHERE state != 'CLOSED'"):
                inc_active.setdefault(row["venue"], []).append((row["state"], row["severity"]))
        except Exception:  # noqa: BLE001
            pass
    unreviewed = [v for v, vp in vpolicy.items()
                  if vp.get("reviewed_at") is None or (vp.get("next_review_at") is not None
                     and vp["next_review_at"].timestamp() < time.time())]

    global_ovr = overrides.get("GLOBAL:GLOBAL", {}).get("mode", "NORMAL")
    venues_out, cred_epochs, cred_rotations = {}, {}, []
    for v in SUPPORTED_VENUES:
        notional, equity, ok, err, key_fp = await _venue_exposure(r, v)
        cep, rotated = await _credential_epoch(pool, v, key_fp)
        if cep is not None:
            cred_epochs[v] = cep
        if rotated:
            cred_rotations.append(v)
        cap_row = caps.get(f"venue:{v}")
        mode, reason, hits = "NORMAL", "ok", []
        cap_val = float(cap_row["max_notional_usdt"]) if cap_row else None
        warn_ratio = float(cap_row["warn_ratio"]) if cap_row else 0.85
        if cap_val is not None:
            if notional >= cap_val:
                mode, reason = "NO_NEW_RISK", f"敞口{notional:.0f}≥上限{cap_val:.0f}U"
                hits.append({"scope": "VENUE_CAP", "mode": mode, "why": reason})
            elif notional >= cap_val * warn_ratio:
                mode, reason = "WATCH", f"敞口{notional:.0f}≥{warn_ratio:.0%}上限"
                hits.append({"scope": "VENUE_CAP", "mode": mode, "why": reason})
        if not ok:
            # 账户快照失败→分类:HARD 权限/风控/冻结=账户限制→NO_NEW(自动保命反射);
            # TRANSPORT 网络限频=不判封号只 WATCH;落 restriction_event 供追溯。
            severity, sig = classify_err(err)
            auto_mode = "NO_NEW_RISK" if severity == "HARD" else "WATCH"
            mode = _stricter(mode, auto_mode)
            reason = f"账户失败[{severity}:{err[:50]}]|" + reason
            hits.append({"scope": "ACCOUNT_FACT", "mode": auto_mode, "why": err[:80]})
            await _persist_restriction(pool, v, severity, sig, err)
        # WithdrawalSentinel(V5 §7.2):提现延迟/连败=平台交易对手风险,叠加取更严格。
        # dedupe 用稳定码 WD:<mode>(reason 含小时数会漂移,避免 restriction_event 行churn)。
        wd_mode, wd_reason = await _withdrawal_mode(r, v)
        if wd_mode != "NORMAL":
            mode = _stricter(mode, wd_mode)
            reason = f"提现哨兵[{wd_reason}]|" + reason
            hits.append({"scope": "WITHDRAWAL", "mode": wd_mode, "why": wd_reason})
            await _persist_restriction(pool, v, "MEDIUM" if wd_mode == "WATCH" else "HARD",
                                       "WITHDRAWAL_DELAY", f"WD:{wd_mode}")
        # 条款登记(V5 §6.1):PROHIBITED=硬闸 FROZEN;UNCLEAR=WATCH 级弱信号(当前书≈HOUSE_RND)
        vp = vpolicy.get(v)
        if vp:
            if vp["arbitrage_status"] == "PROHIBITED":
                mode = _stricter(mode, "FROZEN")
                reason = f"条款禁止套利(venue_policy)|{reason}"
                hits.append({"scope": "VENUE_POLICY", "mode": "FROZEN", "why": "arbitrage=PROHIBITED"})
            elif vp["arbitrage_status"] == "UNCLEAR":
                mode = _stricter(mode, POLICY_UNCLEAR_MODE)
                hits.append({"scope": "VENUE_POLICY", "mode": POLICY_UNCLEAR_MODE, "why": "条款UNCLEAR未复核"})
        # 合并 override(venue 级 + 全局,取最严格)
        vovr_row = overrides.get(f"VENUE:{v}", {})
        vovr = vovr_row.get("mode")
        if vovr:
            mode = _stricter(mode, vovr)
            reason = f"override={vovr};{reason}"
            hits.append({"scope": "OVERRIDE_VENUE", "mode": vovr, "why": str(vovr_row.get("reason"))[:80]})
        if global_ovr != "NORMAL":
            hits.append({"scope": "OVERRIDE_GLOBAL", "mode": global_ovr, "why": ""})
        mode = _stricter(mode, global_ovr)
        # RECOVERY_WATCH 阶梯(V5 §7.3):严重事件出清后逐级恢复,不许直跳 NORMAL
        has_fatal_inc = any(sev == "fatal" for _, sev in inc_active.get(v, []))
        mode, reason, recovery = await _apply_recovery(pool, v, mode, reason, notional, cap_val,
                                                       vovr == "NORMAL", has_fatal_inc)
        if recovery:
            hits.append({"scope": "RECOVERY", "mode": "WATCH",
                         "why": f"阶段{recovery['stage']}额度{int(recovery['allow_pct']*100)}%"})
        # incident_state 与 enforcement_mode 分离(ADR-001 §4.2):事件生命周期≠风险强度
        states = inc_active.get(v, [])
        if any(st in ("OPEN", "ESCALATED") and sev == "fatal" for st, sev in states):
            inc_state = "ACTIVE"
        elif any(st == "RECOVERING" for st, _ in states):
            inc_state = "RECOVERY"
        elif states:
            inc_state = "WATCH"
        else:
            inc_state = "NORMAL"
        venues_out[v] = {
            "mode": mode, "reason": reason,
            "incident_state": inc_state,
            "recovery": recovery,
            "modes_hit": hits,
            "exposure_notional": round(notional, 2), "equity": round(equity, 2),
            "cap_usdt": cap_val, "warn_ratio": warn_ratio,
            "capabilities": _capabilities(mode),
        }

    # NAV haircut:逐 venue trapped = equity × 折价率(按最终有效模式);净 NAV = 总权益 − trapped。
    hc = _haircuts()
    gross = trapped = 0.0
    trapped_by = {}
    for v, d in venues_out.items():
        pct = hc.get(d["mode"], 0.0)
        cut = round(d["equity"] * pct, 2)
        d["haircut_pct"] = pct
        d["trapped_usdt"] = cut
        gross += d["equity"]
        trapped += cut
        if cut > 0:
            trapped_by[v] = cut
    nav = {"gross_equity_usdt": round(gross, 2), "trapped_usdt": round(trapped, 2),
           "net_nav_usdt": round(gross - trapped, 2), "trapped_by_venue": trapped_by}

    body = {
        "ts": int(time.time()),
        "global_mode": global_ovr,
        "venues": venues_out,
        "capped_venues": [v for v, d in venues_out.items() if d["mode"] != "NORMAL"],
        "nav": nav,
        "credential_epochs": cred_epochs,
        "credential_rotations": cred_rotations,
        "policy_registry": {"unreviewed": unreviewed,
                            "prohibited": [v for v, vp in vpolicy.items()
                                           if vp.get("arbitrage_status") == "PROHIBITED"]},
    }
    # (epoch, sequence) 双单调 fencing(ADR-005)+ PG outbox 耐久发布(批次2):
    # 同一事务 bump 版本 + upsert effective_risk_policy 全量快照 + 写 outbox——
    # Redis 清空/C 重启窗口消费者可从 PG 权威读回,旧快照永不复活。
    epoch, version = 1, int(time.time())
    summary = {"policy_epoch": epoch, "policy_version": version, **body}
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "UPDATE risk_policy_version SET policy_version = policy_version + 1, "
                        "updated_at = now() WHERE id = 1 RETURNING policy_epoch, policy_version")
                    if row:
                        epoch, version = int(row["policy_epoch"]), int(row["policy_version"])
                    summary = {"policy_epoch": epoch, "policy_version": version, **body}
                    snap = json.dumps(summary, ensure_ascii=False)
                    await conn.execute(
                        "INSERT INTO effective_risk_policy(id, policy_epoch, policy_version, snapshot) "
                        "VALUES(1, $1, $2, $3::jsonb) ON CONFLICT (id) DO UPDATE SET policy_epoch=$1, "
                        "policy_version=$2, snapshot=$3::jsonb, updated_at=now()", epoch, version, snap)
                    await conn.execute(
                        "INSERT INTO risk_policy_outbox(policy_epoch, policy_version, snapshot) "
                        "VALUES($1, $2, $3::jsonb)", epoch, version, snap)
        except Exception:  # noqa: BLE001  # 表未建/迁移中:降级时间版本,仍发 Redis(不断发布)
            pass
    await r.set(POLICY_KEY, json.dumps(summary, ensure_ascii=False), ex=180)
    await r.set("dcm:risk:nav", json.dumps({**nav, "ts": summary["ts"]}, ensure_ascii=False), ex=180)
    if pool is not None:
        try:
            # Redis 投递成功→标记 outbox 已派发;修剪只留近 500 行
            await pool.execute("UPDATE risk_policy_outbox SET dispatched_at=now() "
                               "WHERE policy_version=$1 AND dispatched_at IS NULL", version)
            await pool.execute("DELETE FROM risk_policy_outbox WHERE id < "
                               "(SELECT COALESCE(max(id),0)-500 FROM risk_policy_outbox)")
        except Exception:  # noqa: BLE001
            pass
    return summary
