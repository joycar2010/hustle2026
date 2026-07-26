from __future__ import annotations
"""
c3s_autopilot — V6 C3.S 影子自主环(shadow autopilot,零真钱)。

定位(用户「接自主环」→选「影子自主环」):
  V6 自主大脑全速活跑——每 cycle 读实时点差 → 独立算净期望 E → 按 **enforce** 决策开/跳,
  但**只写影子账本**,与活着的老 coin 引擎并跑,做实时对账。证 V6 自主决策安全再谈手off。

物理安全边界(与本模块设计强绑,任何改动都不得破坏):
  * 本模块【不 import c3s_writer,不含任何 rpush / emit / dcm:coin:cmd】——从代码层面不可能触发真单。
  * 唯一副作用 = 写 mix 库两张影子表(c3s_autopilot_cycle / c3s_autopilot_decision),additive 可逆。
  * 启停闸 Redis dcm:c3s:v6:autopilot(缺/≠"1" = 空转不评估);kill = 置 0 或 systemctl stop。

E 口径逐字复刻 order_executor._compute_net_expect(order_executor.py:109/614 输入源):
  信号 = spread_short > open_spread;E = 点差捕获 − 利息 − 4腿手续费 − tick 摩擦。
  老引擎自动路径 net_gate_mode 默认 shadow(E≤0 也开);V6 论点 = enforce(E≤0 跳)。
  分岔正是价值:记录「点差正但 E≤0、老引擎开而 V6 跳」的老仓真实 PnL = 避损论点实时验证。

对账基准:engine:1:neteval:{SYM}(老引擎 60s TTL 实时 E 评估,含 decision/gate_mode)。

用法:
  python c3s_autopilot.py ensure      # 建两张影子表(幂等)
  python c3s_autopilot.py cycle       # 跑一轮,打印摘要(不需启停闸,便于验证)
  python c3s_autopilot.py run         # 常驻循环(受 dcm:c3s:v6:autopilot 闸控)
  python c3s_autopilot.py status      # 打印近况摘要
"""
import argparse
import asyncio
import json
import time

import c3s_shadow as S   # 复用 mix_dsn()/_load_env()/MIX_ENV;不引 c3s_writer(杜绝 emit)

ENABLE_KEY = "dcm:c3s:v6:autopilot"
SPREADS_KEY = "dcm:coin:spreads_rt"
PANEL_KEY = "dcm:coin:panel"
PUSHED_KEY = "engine:1:pushed_symbols"
BORROW_KEY = "dcm:borrow:avail"          # borrow-monitor 发布的可借库存 hash {venue:ASSET -> {amount,ts}}
NETEVAL_FMT = "engine:1:neteval:{}"
NETGATE_FMT = "engine:1:netgate:{}"
DEFAULT_INTERVAL = 20.0
TAKER_FEE_RATE = 0.00075   # 与 order_executor 同默认
BORROW_STALE_S = 3600.0    # 库存快照超 1h 视为不可信 -> 保守判不可借


def _redis_url() -> str:
    e = S._load_env(S.MIX_ENV)
    return e.get("MIX_REDIS_URL") or e.get("MIX_REDIS")


def _f(d, k, default=0.0) -> float:
    try:
        v = d.get(k)
        return float(v) if v not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def compute_e(spread_short_pct, notional, irate_daily, hold_hours, f_spot, f_fut, buffer_pct):
    """逐字复刻 order_executor._compute_net_expect。返回 (E, 分项dict)。"""
    n = float(notional or 0)
    cap = float(spread_short_pct or 0) / 100.0 * n
    interest = float(irate_daily or 0) * n * max(1.0, hold_hours) / 24.0
    fee = 2.0 * n * (float(f_spot or 0) + float(f_fut or 0))
    tick = float(buffer_pct or 0) / 100.0 * n
    e = cap - interest - fee - tick
    return e, {"notional": round(n, 4), "spread_capture": round(cap, 4),
               "interest": round(interest, 4), "fee": round(fee, 4),
               "tick": round(tick, 4), "E": round(e, 4)}


DDL = """
CREATE TABLE IF NOT EXISTS c3s_autopilot_cycle (
  id            bigserial PRIMARY KEY,
  cycle_ts      timestamptz DEFAULT now(),
  n_candidates  int, n_signal int, n_v6_open int, n_v6_skip_egate int,
  n_v6_skip_borrow int,
  n_old_eval    int, n_parity_match int, n_parity_diff int,
  spreads_age_s numeric, note text
);
CREATE INDEX IF NOT EXISTS ix_ap_cycle_ts ON c3s_autopilot_cycle(cycle_ts);
ALTER TABLE c3s_autopilot_cycle ADD COLUMN IF NOT EXISTS n_v6_skip_borrow int;

CREATE TABLE IF NOT EXISTS c3s_autopilot_decision (
  id            bigserial PRIMARY KEY,
  cycle_ts      timestamptz DEFAULT now(),
  symbol        text,
  notional      numeric,
  spread_short  numeric,
  open_th       numeric,
  signal        boolean,       -- spread_short > open_th?
  v6_e          numeric,
  v6_decision   text,          -- OPEN / SKIP
  v6_gate       text,          -- signal / e_gate
  v6_break      jsonb,
  old_e         numeric,       -- 老引擎 neteval/netgate E(若同刻评估)
  old_decision  text,
  old_gate_mode text,
  e_parity      boolean,       -- |v6_e-old_e|<1e-4 ?
  note          text
);
CREATE INDEX IF NOT EXISTS ix_ap_dec_ts ON c3s_autopilot_decision(cycle_ts);
CREATE INDEX IF NOT EXISTS ix_ap_dec_sym ON c3s_autopilot_decision(symbol);
"""


async def _read_inputs(rds):
    """读实时点差 + 规则 + 利率 + 黑名单 + 候选集。"""
    sr_raw = await rds.get(SPREADS_KEY)
    sr = json.loads(sr_raw) if sr_raw else {}
    spreads = sr.get("spreads") or {}
    spreads_age = (time.time() - float(sr.get("ts") or 0) / (1000.0 if sr.get("ts", 0) > 1e12 else 1.0)) \
        if sr.get("ts") else None
    panel_raw = await rds.get(PANEL_KEY)
    panel = json.loads(panel_raw) if panel_raw else {}
    rules = panel.get("rules") or {}
    irates = panel.get("interest_rates") or {}
    blacklist = {x.get("symbol") for x in (panel.get("blacklist") or []) if isinstance(x, dict)}
    pushed_raw = await rds.get(PUSHED_KEY)
    try:
        pushed = set(json.loads(pushed_raw)) if pushed_raw else set()
    except Exception:  # noqa: BLE001
        pushed = set()
    # 借币可借库存 hash:{venue:ASSET -> {"amount":x,"ts":t}} -> {ASSET -> amount(新鲜)}
    borrow = {}
    try:
        h = await rds.hgetall(BORROW_KEY)
        now = time.time()
        for k, v in (h or {}).items():
            asset = k.split(":", 1)[1] if ":" in k else k
            try:
                d = json.loads(v)
                amt = float(d.get("amount") or 0)
                ts = float(d.get("ts") or 0)
            except Exception:  # noqa: BLE001
                amt, ts = 0.0, 0.0
            fresh = (now - ts) <= BORROW_STALE_S if ts else False
            # 同一 asset 多 venue 取最大新鲜库存(V6 目前只对 binance 腿建模,取最大即可)
            eff = amt if fresh else 0.0
            if asset not in borrow or eff > borrow[asset]:
                borrow[asset] = eff
    except Exception:  # noqa: BLE001
        borrow = {}
    return spreads, rules, irates, blacklist, pushed, spreads_age, borrow


async def _old_eval(rds, symbol):
    """读老引擎该币实时 E 评估(neteval 优先,netgate 兜底)。"""
    raw = await rds.get(NETEVAL_FMT.format(symbol))
    if raw:
        try:
            d = json.loads(raw)
            return d.get("E"), d.get("decision"), d.get("gate_mode")
        except Exception:  # noqa: BLE001
            pass
    g = await rds.get(NETGATE_FMT.format(symbol))
    if g:
        try:
            return float(str(g).replace("E=", "").replace("U", "")), "reject", "netgate"
        except (TypeError, ValueError):
            return None, "reject", "netgate"
    return None, None, None


async def cycle(pool, rds) -> dict:
    """跑一轮 V6 自主决策(shadow),写账本,返回摘要。

    决策闸序(faithful 复刻老引擎可执行性,非「凑答案」):
      1. signal:  spread_short > open_spread ?
      2. e_gate:  净期望 E > 0 ?  (enforce 语义,老引擎自动路径为 shadow)
      3. borrow:  该币可借库存 * 价格 >= 名义额 ?  (无券 -> 幻影单,必须 SKIP)
    三闸全过才 OPEN。borrow 闸是本轮补进的承重闸——影子环首日实测:
      高点差币多因无券可借(库存=0)才点差高,V6 缺此闸会持续打幻影单。
    """
    spreads, rules, irates, blacklist, pushed, spreads_age, borrow = await _read_inputs(rds)
    open_th_g = _f(rules, "open_spread", 0.5)
    notional_g = _f(rules, "order_amount", 10.0) or 10.0
    f_spot = _f(rules, "taker_fee_spot", TAKER_FEE_RATE) or TAKER_FEE_RATE
    f_fut = _f(rules, "taker_fee_futures", TAKER_FEE_RATE) or TAKER_FEE_RATE
    buffer_pct = _f(rules, "open_spread_buffer", 0.0)
    hold_hours = (_f(rules, "repay_ban_minutes", 30) or 30) / 60.0

    candidates = (pushed & set(spreads.keys())) or set(spreads.keys())
    candidates -= blacklist

    n_signal = n_open = n_skip_e = n_skip_b = n_old = n_match = n_diff = 0
    rows = []
    for sym in candidates:
        sp = spreads.get(sym) or {}
        try:
            ss = float(sp.get("spread_short"))
        except (TypeError, ValueError):
            continue
        signal = ss > open_th_g
        coin = sym[:-4] if sym.endswith("USDT") else sym
        irate = _f(irates, coin, 0.0)
        # 可借性:库存(coin 单位)* 现货卖价 >= 名义额;库存缺/陈旧 -> 0 -> 不可借
        try:
            price = float(sp.get("spot_ask") or sp.get("spot_bid") or 0)
        except (TypeError, ValueError):
            price = 0.0
        borrow_amt = float(borrow.get(coin, 0.0))
        borrow_notional = borrow_amt * price
        borrow_ok = borrow_notional >= notional_g

        v6_e = None
        v6_break = None
        v6_decision = "SKIP"
        v6_gate = "signal"
        if signal:
            n_signal += 1
            v6_e, v6_break = compute_e(ss, notional_g, irate, hold_hours, f_spot, f_fut, buffer_pct)
            if v6_e <= 0:
                v6_decision = "SKIP"; v6_gate = "e_gate"; n_skip_e += 1
            elif not borrow_ok:
                v6_decision = "SKIP"; v6_gate = "borrow_unavail"; n_skip_b += 1
            else:
                v6_decision = "OPEN"; v6_gate = "open"; n_open += 1
            if v6_break is not None:
                v6_break["borrow_amt"] = round(borrow_amt, 6)
                v6_break["borrow_notional"] = round(borrow_notional, 4)
                v6_break["borrow_ok"] = borrow_ok

        old_e, old_dec, old_mode = await _old_eval(rds, sym)
        if old_e is not None:
            n_old += 1
            if v6_e is not None:
                if abs(float(v6_e) - float(old_e)) < 1e-4:
                    n_match += 1
                else:
                    n_diff += 1

        # 只记有信息量的行:信号触发 OR 老引擎同刻评估过
        if signal or old_e is not None:
            e_parity = (v6_e is not None and old_e is not None
                        and abs(float(v6_e) - float(old_e)) < 1e-4)
            rows.append((sym, notional_g, ss, open_th_g, signal,
                         v6_e, v6_decision, v6_gate,
                         json.dumps(v6_break, ensure_ascii=False) if v6_break else None,
                         old_e, old_dec, old_mode, e_parity))

    async with pool.acquire() if hasattr(pool, "acquire") else _NullCtx(pool) as con:
        c = con
        await c.execute(
            "INSERT INTO c3s_autopilot_cycle(n_candidates,n_signal,n_v6_open,n_v6_skip_egate,"
            "n_v6_skip_borrow,n_old_eval,n_parity_match,n_parity_diff,spreads_age_s,note) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            len(candidates), n_signal, n_open, n_skip_e, n_skip_b, n_old, n_match, n_diff,
            round(spreads_age, 1) if spreads_age is not None else None,
            "shadow-autopilot")
        for r in rows:
            await c.execute(
                "INSERT INTO c3s_autopilot_decision(symbol,notional,spread_short,open_th,signal,"
                "v6_e,v6_decision,v6_gate,v6_break,old_e,old_decision,old_gate_mode,e_parity) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13)", *r)

    return {"candidates": len(candidates), "signal": n_signal, "v6_open": n_open,
            "v6_skip_egate": n_skip_e, "v6_skip_borrow": n_skip_b, "old_eval": n_old,
            "parity_match": n_match, "parity_diff": n_diff,
            "borrowable_assets": sum(1 for a in borrow.values() if a > 0),
            "spreads_age_s": round(spreads_age, 1) if spreads_age is not None else None,
            "detail_rows": len(rows)}


class _NullCtx:
    def __init__(self, obj): self.obj = obj
    async def __aenter__(self): return self.obj
    async def __aexit__(self, *a): return False


async def ensure(pool):
    await pool.execute(DDL)


async def status(pool, rds) -> dict:
    en = await rds.get(ENABLE_KEY)
    last = await pool.fetchrow("SELECT * FROM c3s_autopilot_cycle ORDER BY id DESC LIMIT 1")
    tot = await pool.fetchval("SELECT count(*) FROM c3s_autopilot_cycle")
    # 迄今 V6 跳而信号在的累计(避损候选)
    agg = await pool.fetchrow(
        "SELECT count(*) FILTER(WHERE v6_decision='OPEN') v6_open, "
        "count(*) FILTER(WHERE signal AND v6_gate='e_gate') v6_skip_egate, "
        "count(*) FILTER(WHERE signal AND v6_gate='borrow_unavail') v6_skip_borrow, "
        "count(*) FILTER(WHERE e_parity) parity_ok, "
        "count(*) FILTER(WHERE old_e IS NOT NULL) old_evals "
        "FROM c3s_autopilot_decision")
    return {"enabled": str(en) == "1", "cycles_total": tot,
            "last_cycle": dict(last) if last else None,
            "decision_agg": dict(agg) if agg else None,
            "note": "影子自主环:只写账本不触发真单;enabled=0 即空转。对账 vs 老引擎 neteval。"}


async def run(pool, rds, interval=DEFAULT_INTERVAL):
    await ensure(pool)
    while True:
        try:
            en = await rds.get(ENABLE_KEY)
            if str(en) == "1":
                s = await cycle(pool, rds)
                print(json.dumps({"ts": int(time.time()), **s}, ensure_ascii=False), flush=True)
            # 闸关则空转(不评估、不写)
        except Exception as e:  # noqa: BLE001 —— 单轮异常不拖垮常驻循环
            print(json.dumps({"ts": int(time.time()), "error": f"{type(e).__name__}: {e}"},
                             ensure_ascii=False), flush=True)
        await asyncio.sleep(interval)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ensure", "cycle", "run", "status"])
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    args = ap.parse_args()
    import asyncpg
    import redis.asyncio as R
    pool = await asyncpg.connect(S.mix_dsn(), timeout=10)
    rds = R.from_url(_redis_url(), decode_responses=True)
    try:
        if args.cmd == "ensure":
            await ensure(pool); print("ensure OK: c3s_autopilot_cycle + c3s_autopilot_decision")
        elif args.cmd == "cycle":
            await ensure(pool)
            print(json.dumps(await cycle(pool, rds), ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "status":
            print(json.dumps(await status(pool, rds), ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "run":
            await run(pool, rds, args.interval)
    finally:
        await pool.close(); await rds.aclose()


if __name__ == "__main__":
    asyncio.run(main())
