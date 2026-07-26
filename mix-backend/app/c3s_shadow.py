from __future__ import annotations
"""
c3s_shadow — V6 C3.S 影子写路 · S0 地面实况账本(read-only capture)。

纪律(与 dcm-coin-bridge 一致):
  * 对 coin_legacy **只读**(dcm_ro 账号),绝不写 coin 库、绝不下任何单。
  * 只写 mix 库的新表 c3s_ground_truth(additive,可逆:DROP TABLE 即回滚)。
  * 数据面纪律:归一/透传,不判断。判断留给 S1 影子决策器。

作用:把老 coin 引擎每个 C3.S 持仓的**真实生命周期**(BORROW→SPOT_SELL→
FUTURES_LONG→…→REPAY 的逐腿账 + 决策上下文 open/close spread、expected_e)
落成一张 mix 侧可查的地面实况表,作为 S1 决策级平价对账的 diff 靶。

用法:
  python c3s_shadow.py ensure       # 只建表
  python c3s_shadow.py backfill      # 全量回填(幂等 upsert by position_id)
  python c3s_shadow.py backfill --since 2026-07-01
  python c3s_shadow.py stat          # 打印账本统计
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# ── DSN 解析 ────────────────────────────────────────────────────────────────
MIX_ENV = os.environ.get("MIX_ENV_PATH", "/data/mix/backend/.env")
BRIDGE_ENV = os.environ.get("BRIDGE_ENV_PATH", "/data/coin/dcmbridge/.env")


def _load_env(path: str) -> dict:
    e = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return e


def _libpq_to_url(kv: str) -> str:
    """把 libpq keyword DSN(dbname=.. user=.. password=.. host=..)转 asyncpg URL。"""
    d = {}
    for tok in kv.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    user = d.get("user", "")
    pw = d.get("password", "")
    host = d.get("host", "127.0.0.1")
    port = d.get("port", "5432")
    db = d.get("dbname", "")
    auth = user + (f":{pw}" if pw else "")
    return f"postgresql://{auth}@{host}:{port}/{db}"


def mix_dsn() -> str:
    dsn = os.environ.get("MIX_MAIN_DSN") or _load_env(MIX_ENV).get("MIX_MAIN_DSN")
    if not dsn:
        raise SystemExit("MIX_MAIN_DSN not found")
    return dsn


def coin_ro_dsn() -> str:
    # 优先从 dcmbridge .env 读只读账号(密码会轮换,不硬编码)
    kv = os.environ.get("COIN_PG_DSN") or _load_env(BRIDGE_ENV).get("COIN_PG_DSN")
    if kv:
        return _libpq_to_url(kv)
    raise SystemExit("COIN_PG_DSN (dcm_ro) not found in bridge .env")


# ── DDL ─────────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS c3s_ground_truth (
  position_id      bigint PRIMARY KEY,
  symbol           text NOT NULL,
  user_id          integer,
  sub_account_id   integer,
  status           text,
  hedge_account    text,
  open_spread      numeric,
  close_spread     numeric,
  expected_e       numeric,
  open_usdt_amount numeric,
  borrow_interest_rate numeric,
  e_breakdown      jsonb,
  borrow_qty       numeric,
  futures_long_qty numeric,
  realized_pnl     numeric,
  opened_at        timestamptz,
  closed_at        timestamptz,
  created_at       timestamptz,
  leg_actions      jsonb,
  leg_count        integer,
  first_leg_at     timestamptz,
  last_leg_at      timestamptz,
  captured_at      timestamptz DEFAULT now(),
  source           text DEFAULT 'coin_legacy'
);
CREATE INDEX IF NOT EXISTS ix_c3s_gt_symbol  ON c3s_ground_truth(symbol);
CREATE INDEX IF NOT EXISTS ix_c3s_gt_created ON c3s_ground_truth(created_at);
CREATE INDEX IF NOT EXISTS ix_c3s_gt_status  ON c3s_ground_truth(status);
ALTER TABLE c3s_ground_truth ADD COLUMN IF NOT EXISTS open_usdt_amount numeric;
ALTER TABLE c3s_ground_truth ADD COLUMN IF NOT EXISTS borrow_interest_rate numeric;
ALTER TABLE c3s_ground_truth ADD COLUMN IF NOT EXISTS e_breakdown jsonb;
"""

UPSERT = """
INSERT INTO c3s_ground_truth
  (position_id,symbol,user_id,sub_account_id,status,hedge_account,open_spread,
   close_spread,expected_e,open_usdt_amount,borrow_interest_rate,e_breakdown,
   borrow_qty,futures_long_qty,realized_pnl,opened_at,
   closed_at,created_at,leg_actions,leg_count,first_leg_at,last_leg_at,captured_at,source)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15,$16,$17,$18,$19::jsonb,$20,$21,$22,now(),'coin_legacy')
ON CONFLICT (position_id) DO UPDATE SET
  status=EXCLUDED.status, hedge_account=EXCLUDED.hedge_account,
  open_spread=EXCLUDED.open_spread, close_spread=EXCLUDED.close_spread,
  expected_e=EXCLUDED.expected_e, open_usdt_amount=EXCLUDED.open_usdt_amount,
  borrow_interest_rate=EXCLUDED.borrow_interest_rate, e_breakdown=EXCLUDED.e_breakdown,
  borrow_qty=EXCLUDED.borrow_qty,
  futures_long_qty=EXCLUDED.futures_long_qty, realized_pnl=EXCLUDED.realized_pnl,
  opened_at=EXCLUDED.opened_at, closed_at=EXCLUDED.closed_at,
  leg_actions=EXCLUDED.leg_actions, leg_count=EXCLUDED.leg_count,
  first_leg_at=EXCLUDED.first_leg_at, last_leg_at=EXCLUDED.last_leg_at,
  captured_at=now();
"""


def _s(v):
    return None if v is None else str(v)


async def ensure(mix):
    await mix.execute(DDL)


async def backfill(mix, coin, since: str | None) -> dict:
    where = ""
    args = []
    if since:
        where = "WHERE created_at >= $1"
        args = [datetime.fromisoformat(since).replace(tzinfo=timezone.utc)]
    positions = await coin.fetch(f"""
        SELECT id,symbol,user_id,sub_account_id,status,hedge_account,open_spread,
               close_spread,expected_e,open_usdt_amount,borrow_interest_rate,e_breakdown,
               borrow_qty,futures_long_qty,realized_pnl,
               opened_at,closed_at,created_at
        FROM positions {where} ORDER BY id
    """, *args)
    if not positions:
        return {"positions": 0, "upserted": 0}
    pids = [p["id"] for p in positions]
    # 逐腿账:一把拉齐所有相关 trade_logs
    logs = await coin.fetch("""
        SELECT position_id,action,side,quantity,price,status,order_id,latency_ms,created_at
        FROM trade_logs WHERE position_id = ANY($1::bigint[]) ORDER BY position_id, created_at
    """, pids)
    by_pid: dict[int, list] = {}
    for lg in logs:
        by_pid.setdefault(lg["position_id"], []).append(lg)

    upserted = 0
    for p in positions:
        legs = by_pid.get(p["id"], [])
        leg_actions = [{
            "action": lg["action"], "side": lg["side"],
            "qty": _s(lg["quantity"]), "price": _s(lg["price"]),
            "status": lg["status"], "order_id": lg["order_id"],
            "latency_ms": lg["latency_ms"],
            "ts": lg["created_at"].isoformat() if lg["created_at"] else None,
        } for lg in legs]
        first_leg = legs[0]["created_at"] if legs else None
        last_leg = legs[-1]["created_at"] if legs else None
        eb = p["e_breakdown"]
        eb = eb if (eb is None or isinstance(eb, str)) else json.dumps(eb)
        await mix.execute(
            UPSERT,
            p["id"], p["symbol"], p["user_id"], p["sub_account_id"], p["status"],
            p["hedge_account"], p["open_spread"], p["close_spread"], p["expected_e"],
            p["open_usdt_amount"], p["borrow_interest_rate"], eb,
            p["borrow_qty"], p["futures_long_qty"], p["realized_pnl"],
            p["opened_at"], p["closed_at"], p["created_at"],
            json.dumps(leg_actions), len(leg_actions), first_leg, last_leg,
        )
        upserted += 1
    return {"positions": len(positions), "upserted": upserted}


# ── S1 影子决策器 ────────────────────────────────────────────────────────────
# V6 C3.S 开仓决策(纯函数,复现 worker.py 借币/对冲闸 + order_executor E 闸)。
# 输入 = 从地面实况持仓归一出的经济上下文;输出 = V6 意图(OPEN / SKIP+reason)。
# 两模式:shadow(与老引擎同,仅记录)/ enforce(E>0 硬闸 + 自杀组合校验)。
TAKER_FEE_RATE = 0.00075   # order_executor.TAKER_FEE_RATE


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def recompute_e(notional, spread_pct, irate_daily, hold_hours, f_spot, f_fut, buffer_pct):
    """字节级复现 order_executor._compute_net_expect。返回 (E, 分项dict)。"""
    n = _f(notional) or 0.0
    cap = (_f(spread_pct) or 0.0) / 100.0 * n
    interest = (_f(irate_daily) or 0.0) * n * max(1.0, _f(hold_hours) or 1.0) / 24.0
    fee = 2.0 * n * ((_f(f_spot) or 0.0) + (_f(f_fut) or 0.0))
    tick = (_f(buffer_pct) or 0.0) / 100.0 * n
    e = cap - interest - fee - tick
    return e, {"notional_usdt": round(n, 4), "spread_capture": round(cap, 4),
               "interest_cost": round(interest, 4), "fee_cost": round(fee, 4),
               "tick_cost": round(tick, 4), "funding_expect": 0.0, "E": round(e, 4)}


def normalize_inputs(gt: dict) -> dict:
    """把 c3s_ground_truth 行 + 其 e_breakdown 归一成决策输入。
    spread_pct 优先从 e_breakdown.spread_capture 反解(=开仓时真实点差),回退 open_spread。"""
    eb = gt.get("e_breakdown") or {}
    if isinstance(eb, str):
        try:
            eb = json.loads(eb)
        except Exception:
            eb = {}
    notional = eb.get("notional_usdt") or _f(gt.get("open_usdt_amount"))
    spread_pct = None
    if notional and eb.get("spread_capture") is not None:
        spread_pct = eb["spread_capture"] / notional * 100.0
    if spread_pct is None:
        spread_pct = _f(gt.get("open_spread"))
    return {
        "notional": notional,
        "spread_pct": spread_pct,
        "irate_daily": _f(gt.get("borrow_interest_rate")),
        "hold_hours": eb.get("hold_hours") or 1.0,
        "f_spot": TAKER_FEE_RATE, "f_fut": TAKER_FEE_RATE, "buffer_pct": eb.get("tick_cost") and 0.0 or 0.0,
        "open_spread": _f(gt.get("open_spread")),
        "close_spread": _f(gt.get("close_spread")),
        "e_stored": _f(gt.get("expected_e")),
        "realized_pnl": _f(gt.get("realized_pnl")),
    }


def decide(inp: dict, mode: str) -> dict:
    """V6 C3.S 开仓决策。mode ∈ {shadow, enforce}。返回意图 dict。
    gate ∈ {no_data, suicide, E, none}。no_data(缺经济上下文)= 不可判,独立于 E 闸,
    不计入经济背离归因 —— 否则老仓(e_breakdown 上线前)会被误当"E<=0"虚增拒开。"""
    n = inp["notional"]
    if not n:  # 无 notional → E 不可判(数据缺失,非经济结论)
        return {"decision": "SKIP", "reason": "无经济上下文(notional缺,E不可判)",
                "e": None, "gate": "no_data"}
    e, br = recompute_e(n, inp["spread_pct"], inp["irate_daily"],
                        inp["hold_hours"], inp["f_spot"], inp["f_fut"], inp["buffer_pct"])
    open_th, close_th = inp["open_spread"], inp["close_spread"]
    # 自杀组合校验(worker.py:499-505)—— 两模式都开(安全护栏,非经济闸)
    if open_th is not None and close_th is not None and open_th < close_th:
        return {"decision": "SKIP", "reason": f"配置冲突 open({open_th})<close({close_th})",
                "e": round(e, 4), "gate": "suicide"}
    # E 闸(order_executor net_gate,enforce 才硬拦)
    if mode == "enforce" and e <= 0:
        return {"decision": "SKIP", "reason": f"E闸 E={round(e,4)}<=0", "e": round(e, 4), "gate": "E"}
    return {"decision": "OPEN", "reason": "pass", "e": round(e, 4), "gate": "none"}


DDL_DECISION = """
CREATE TABLE IF NOT EXISTS c3s_shadow_decision (
  position_id   bigint NOT NULL,
  mode          text   NOT NULL,
  v6_decision   text,
  v6_reason     text,
  gate          text,
  e_recomputed  numeric,
  e_stored      numeric,
  e_match       boolean,
  actual        text,
  agrees        boolean,
  realized_pnl  numeric,
  symbol        text,
  decided_at    timestamptz DEFAULT now(),
  PRIMARY KEY (position_id, mode)
);
CREATE INDEX IF NOT EXISTS ix_c3s_dec_mode ON c3s_shadow_decision(mode);
"""

UPSERT_DECISION = """
INSERT INTO c3s_shadow_decision
  (position_id,mode,v6_decision,v6_reason,gate,e_recomputed,e_stored,e_match,
   actual,agrees,realized_pnl,symbol,decided_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,now())
ON CONFLICT (position_id,mode) DO UPDATE SET
  v6_decision=EXCLUDED.v6_decision, v6_reason=EXCLUDED.v6_reason, gate=EXCLUDED.gate,
  e_recomputed=EXCLUDED.e_recomputed, e_stored=EXCLUDED.e_stored, e_match=EXCLUDED.e_match,
  actual=EXCLUDED.actual, agrees=EXCLUDED.agrees, realized_pnl=EXCLUDED.realized_pnl,
  symbol=EXCLUDED.symbol, decided_at=now();
"""


async def replay(mix, modes=("shadow", "enforce")) -> dict:
    """对 c3s_ground_truth 每个持仓回放 V6 决策,写 c3s_shadow_decision,返回汇总。
    actual = OPEN(账本中每个持仓都真开过);对比 = V6 是否也决定 OPEN。"""
    await mix.execute(DDL_DECISION)
    rows = await mix.fetch("""SELECT position_id,symbol,open_spread,close_spread,expected_e,
                                     open_usdt_amount,borrow_interest_rate,borrow_qty,
                                     realized_pnl,e_breakdown FROM c3s_ground_truth""")
    summary = {m: {"n": 0, "OPEN": 0, "SKIP": 0, "agree": 0, "diverge": 0,
                   "e_match": 0, "gates": {}, "gate_pnl": {}, "econ_diverge": 0,
                   "econ_diverge_pnl_sum": 0.0, "all_diverge_pnl_sum": 0.0,
                   "econ_diverge_examples": []} for m in modes}
    for r in rows:
        gt = dict(r)
        inp = normalize_inputs(gt)
        actual = "OPEN"   # 账本中每个持仓都真开过 → 地面实况恒为 OPEN
        for m in modes:
            d = decide(inp, m)
            e_rec = d["e"]
            e_match = (e_rec is not None and inp["e_stored"] is not None
                       and abs(e_rec - inp["e_stored"]) <= 0.001)
            agrees = (d["decision"] == actual)
            await mix.execute(UPSERT_DECISION, gt["position_id"], m, d["decision"], d["reason"],
                              d["gate"], e_rec, inp["e_stored"], e_match, actual, agrees,
                              inp["realized_pnl"], gt["symbol"])
            s = summary[m]
            s["n"] += 1
            s[d["decision"]] += 1
            s["agree" if agrees else "diverge"] += 1
            s["gates"][d["gate"]] = s["gates"].get(d["gate"], 0) + 1
            s["gate_pnl"][d["gate"]] = round(
                s["gate_pnl"].get(d["gate"], 0.0) + (inp["realized_pnl"] or 0.0), 4)
            if e_match:
                s["e_match"] += 1
            if not agrees:
                pnl = inp["realized_pnl"] or 0.0
                s["all_diverge_pnl_sum"] += pnl
                # 只有"有经济上下文的真拒开"(E 闸/自杀闸)才算经济背离归因;
                # no_data(缺料)不可判,排除,避免虚增。
                if d["gate"] in ("E", "suicide"):
                    s["econ_diverge"] += 1
                    s["econ_diverge_pnl_sum"] += pnl
                    if len(s["econ_diverge_examples"]) < 6:
                        s["econ_diverge_examples"].append(
                            {"pos": gt["position_id"], "sym": gt["symbol"], "reason": d["reason"],
                             "E": e_rec, "realized_pnl": round(pnl, 4)})
    for m in modes:
        summary[m]["econ_diverge_pnl_sum"] = round(summary[m]["econ_diverge_pnl_sum"], 4)
        summary[m]["all_diverge_pnl_sum"] = round(summary[m]["all_diverge_pnl_sum"], 4)
    return summary


async def stat(mix) -> dict:
    tot = await mix.fetchval("SELECT count(*) FROM c3s_ground_truth")
    by_status = await mix.fetch(
        "SELECT status,count(*) n FROM c3s_ground_truth GROUP BY 1 ORDER BY 2 DESC")
    rng = await mix.fetchrow(
        "SELECT min(created_at) lo, max(created_at) hi, sum(leg_count) legs FROM c3s_ground_truth")
    top_sym = await mix.fetch(
        "SELECT symbol,count(*) n FROM c3s_ground_truth GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
    e_neg = await mix.fetchval(
        "SELECT count(*) FROM c3s_ground_truth WHERE expected_e < 0")
    e_known = await mix.fetchval(
        "SELECT count(*) FROM c3s_ground_truth WHERE expected_e IS NOT NULL")
    return {
        "rows": tot,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "created_range": [str(rng["lo"]), str(rng["hi"])],
        "total_legs": rng["legs"],
        "top_symbols": {r["symbol"]: r["n"] for r in top_sym},
        "expected_e_negative": f"{e_neg}/{e_known}",
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ensure", "backfill", "stat", "replay"])
    ap.add_argument("--since", default=None)
    args = ap.parse_args()

    import asyncpg
    mix = await asyncpg.connect(mix_dsn(), timeout=10)
    try:
        if args.cmd == "ensure":
            await ensure(mix)
            print("ensure OK: c3s_ground_truth ready")
        elif args.cmd == "backfill":
            await ensure(mix)
            coin = await asyncpg.connect(coin_ro_dsn(), timeout=10)
            try:
                res = await backfill(mix, coin, args.since)
            finally:
                await coin.close()
            print("backfill:", json.dumps(res, ensure_ascii=False))
            print("stat:", json.dumps(await stat(mix), ensure_ascii=False, indent=2))
        elif args.cmd == "replay":
            res = await replay(mix)
            print("replay summary:", json.dumps(res, ensure_ascii=False, indent=2))
        elif args.cmd == "stat":
            print(json.dumps(await stat(mix), ensure_ascii=False, indent=2))
    finally:
        await mix.close()


if __name__ == "__main__":
    asyncio.run(main())
