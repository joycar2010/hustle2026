"""dcm-exec-autopilot —— L0 全自动开仓层(2026-07-25 用户拍板:开L0/单笔30U/日预算100U/授权自动平仓)。

三层授权架构的最底层(V4.0"武装绝不自动"铁律的首次受控突破):
  L0 本服务:小额全自动(事后通报,不事前审批)
  L1 快线:30~200U mixadmin 人工点击(现状)
  L2 提案:>200U DRY_RUN+TOTP 双人审批(骨架已有)

L0 准入(全部满足才动):
  ① 总开关 dcm:exec:autopilot:config {"enabled":true,"per_order_usdt":30,"daily_budget_usdt":100}
  ② policy global_mode==NORMAL(kill 按下=NO_NEW_RISK→本层自停,双保险:runner can_open 也会拦)
  ③ 候选来自 dcm:exec:opener(已过 E闸/深度硬闸/三重配额/冷却/persist≥3轮/逐venue policy)
  ④ risk_adjusted_e_bps > MIN_RA_E(默认30)且 depth_verdict==OK
  ⑤ 日预算未耗尽(Redis 计数 dcm:exec:autopilot:spent:{UTC日},incr 预扣)
  ⑥ 单币尝试冷却(attempt 键 1h,防 runner 拒单后每轮重试)
执行:入快线队列(runner 仍是唯一执行者,B侧机器闸不可绕)→成交后把 manager pair 翻
  **armed + signal_source=route**=自动生命周期:advisor 路由 off→manager 自动平仓,
  平仓打 opener 冷却戳(1h)+persist(3轮)双重阻尼吸收路由震荡。
每笔自动开仓 Notifier warn 通报(飞书+跑马灯);连续失败≥3 → fatal 告警+自动停用本层。
"""
import asyncio
import datetime as dt
import json
import os
import sys
import time

import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/packages/dcm-common")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
INTERVAL = int(os.environ.get("DCM_AUTOPILOT_INTERVAL_SEC", "60"))
MIN_RA_E = float(os.environ.get("DCM_AUTOPILOT_MIN_RA_E_BPS", "30"))
CONFIG_KEY = "dcm:exec:autopilot:config"
Q_REQ = "dcm:exec:fastlane:req"

try:
    from dcm_common.notify import Notifier, feishu_from_env
    _notifier = Notifier(REDIS_URL, "autopilot", feishu=feishu_from_env())
except Exception:  # noqa: BLE001
    _notifier = None

_DEFAULTS = {"enabled": False, "per_order_usdt": 30.0, "daily_budget_usdt": 100.0}


async def _config(r):
    try:
        cfg = json.loads(await r.get(CONFIG_KEY) or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}
    out = dict(_DEFAULTS)
    for k, dv in _DEFAULTS.items():
        if k in cfg and cfg[k] is not None:
            try:
                out[k] = bool(cfg[k]) if isinstance(dv, bool) else float(cfg[k])
            except (ValueError, TypeError):
                pass
    return out


def _notify(key, title, msg, level="warn"):
    if _notifier is None:
        return
    try:
        _notifier.fire(key, title, msg, level=level, marquee=True, color="#F0B90B")
    except Exception as e:  # noqa: BLE001
        print("notify err", repr(e)[:80])


async def _disable_self(r, why):
    """连续失败熔断:停用本层+fatal 告警(邮件升级)。"""
    try:
        cfg = json.loads(await r.get(CONFIG_KEY) or "{}")
        cfg["enabled"] = False
        cfg["disabled_reason"] = f"{why} @ {dt.datetime.utcnow().isoformat()}"
        await r.set(CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    _notify("self-disable", "L0 自动开仓已熔断停用", f"{why}——已置 enabled=false,人工审查后重新开启", level="fatal")


async def run_round(r, fail_streak):
    cfg = await _config(r)
    if not cfg["enabled"]:
        return fail_streak, "disabled"
    # kill/全局降级双保险
    try:
        pol = json.loads(await r.get("dcm:risk:policy") or "{}")
        if pol.get("global_mode") != "NORMAL":
            return fail_streak, f"global_mode={pol.get('global_mode')}(暂停)"
    except Exception:  # noqa: BLE001
        return fail_streak, "policy读取失败(保守跳过)"

    op = json.loads(await r.get("dcm:exec:opener") or "{}")
    cands = op.get("candidates") or []
    if not cands:
        return fail_streak, "无候选"

    day = dt.datetime.utcnow().strftime("%Y%m%d")
    spent_key = f"dcm:exec:autopilot:spent:{day}"
    spent = float(await r.get(spent_key) or 0)

    acted = []
    for c in cands:
        sym = c.get("symbol")
        ra_e = float(c.get("risk_adjusted_e_bps") or -999)
        if ra_e <= MIN_RA_E or c.get("depth_verdict") != "OK":
            continue
        if await r.get(f"dcm:exec:autopilot:attempt:{sym}"):
            continue   # 1h 尝试冷却(拒单/成交都不立刻重试)
        notional = min(cfg["per_order_usdt"], float(c.get("target_notional_usdt") or 0))
        if notional < 5:
            continue
        if spent + notional > cfg["daily_budget_usdt"]:
            return fail_streak, f"日预算耗尽({spent:.0f}+{notional:.0f}>{cfg['daily_budget_usdt']:.0f}U)"
        # 预扣+尝试冷却
        spent = float(await r.incrbyfloat(spent_key, notional))
        await r.expire(spent_key, 172800)
        await r.setex(f"dcm:exec:autopilot:attempt:{sym}", 3600, "1")
        rid = f"fl-auto-{sym}-{int(time.time())}"
        req = {"req_id": rid, "symbol": sym, "venue_long": c["venue_long"],
               "venue_short": c["venue_short"], "notional_usdt": round(notional, 2),
               "operator": "autopilot-L0",
               "source": f"L0自动开仓 ra_e={ra_e}bps persist={c.get('persist_rounds')}"}
        await r.rpush(Q_REQ, json.dumps(req, ensure_ascii=False))
        # 等 runner 结果(最多60s)
        res = None
        for _ in range(30):
            await asyncio.sleep(2)
            raw = await r.get(f"dcm:exec:fastlane:res:{rid}")
            if raw:
                res = json.loads(raw)
                break
        if res and res.get("ok"):
            fail_streak = 0
            # 自动生命周期:armed + route 源(advisor 路由 off → manager 自动平)
            try:
                mc = json.loads(await r.get("dcm:exec:manager:config") or "{}")
                pc = mc.setdefault("pairs", {}).get(sym)
                if pc:
                    pc["mode"] = "armed"
                    pc["signal_source"] = "route"
                    await r.set("dcm:exec:manager:config", json.dumps(mc, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print("armed flip err", repr(e)[:80])
            acted.append(f"{sym}@{notional:.0f}U")
            _notify(f"open:{sym}", f"L0自动开仓 {sym}",
                    f"{c['venue_long']}多/{c['venue_short']}空 {notional:.0f}U/腿 "
                    f"ra_e={ra_e}bps saga={res.get('saga_id')} intent={res.get('intent_id')} "
                    f"(armed+route源,advisor撤路由即自动平;日已用{spent:.0f}/{cfg['daily_budget_usdt']:.0f}U)")
        else:
            # 拒单退预算(attempt 冷却保留防重试风暴)
            await r.incrbyfloat(spent_key, -notional)
            fail_streak += 1
            reason = (res or {}).get("reason", "timeout")
            print(f"autopilot: {sym} REJECTED {reason}")
            _notify(f"reject:{sym}", f"L0自动开仓被拒 {sym}", f"{reason}(runner机器闸,预算已退)")
            if fail_streak >= 3:
                await _disable_self(r, f"连续{fail_streak}笔被拒(最后:{sym} {reason})")
                return fail_streak, "熔断停用"
    return fail_streak, (f"开仓{acted}" if acted else "候选未达L0门槛")


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    print(f"autopilot: up interval={INTERVAL}s min_ra_e={MIN_RA_E}bps (L0全自动层,config={CONFIG_KEY})")
    fail_streak = 0
    while True:
        try:
            fail_streak, note = await run_round(r, fail_streak)
            cfg = await _config(r)
            await r.set("dcm:hb:exec-autopilot", json.dumps({
                "ts": int(time.time()), "pid": os.getpid(), "service": "exec-autopilot",
                "enabled": cfg["enabled"], "note": note[:120]}), ex=300)
            print(f"autopilot: {note}")
        except Exception as e:  # noqa: BLE001
            print("autopilot err:", repr(e)[:150])
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
