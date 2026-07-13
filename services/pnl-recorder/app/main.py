"""pnl-recorder(B 机,key 只在 B):PnL 三表持久化——五所账单逐笔入账 + 权益快照。

- 每 DCM_PNL_INTERVAL_SEC(300s) 按游标增量拉五所账单(资金费/手续费/已实现盈亏),
  (venue, ext_id) 唯一去重幂等入 income_records;游标=该所本轮最大 ts-60s(重叠窗防漏);
- 每小时写 equity_snapshots(从 dcm:account:* 读,已是实盘真相);
- 逐所失败隔离,失败只告日志绝不写假数据(coin 学费:失败静默返空=假巨亏);
- 汇总写 dcm:pnl:summary 供面板(累计资金费/手续费/PNL+今日)。
"""
import asyncio
import json
import logging
import os
import time

import asyncpg
import httpx
import redis.asyncio as aioredis

from dcm_common.exchange_bills import fetch_income
from dcm_common.notify import Notifier, feishu_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pnl-recorder")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_PNL_INTERVAL_SEC", "300"))
BOOTSTRAP_HOURS = int(os.environ.get("DCM_PNL_BOOTSTRAP_HOURS", "24"))

VENUE_CFG = {
    "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
    "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
            "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
    "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
    "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
               "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
}


async def _strategy_tagger(pool):
    """归因打标(写入时定案,消费端不再猜):S1=basis 名下币 / S2=dualperp / ''=未归因。
    时间局部性:按写入当时的在管归属认领——历史行保持当时的标签,不被今后换手改写。"""
    bs = {r["symbol"] for r in await pool.fetch("SELECT DISTINCT symbol FROM basis_positions")}
    dp = {r["symbol"] for r in await pool.fetch("SELECT DISTINCT symbol FROM dualperp_positions")}

    def tag(sym: str) -> str:
        if sym in bs:
            return "S1"
        if sym in dp:
            return "S2"
        return ""
    return tag


async def pull_venue(cli, pool, venue, cfg) -> tuple[int, str]:
    cur = await pool.fetchval("SELECT last_ts_ms FROM income_cursors WHERE venue=$1", venue)
    since = int(cur) if cur else int((time.time() - BOOTSTRAP_HOURS * 3600) * 1000)
    try:
        recs = await fetch_income(cli, venue, cfg, since)
    except Exception as e:
        return 0, f"{e!r}"[:120]
    tag = await _strategy_tagger(pool)
    ins = 0
    max_ts = since
    for r in recs:
        if not r.ext_id:
            continue
        max_ts = max(max_ts, r.ts_ms)
        status = await pool.execute(
            "INSERT INTO income_records(venue,ext_id,symbol,itype,amount,ts,raw,strategy_code) "
            "VALUES($1,$2,$3,$4,$5,to_timestamp($6/1000.0),$7,$8) ON CONFLICT (venue,ext_id) DO NOTHING",
            r.venue, r.ext_id, r.symbol, r.itype, r.amount, r.ts_ms,
            json.dumps(r.raw, ensure_ascii=False, default=str), tag(r.symbol))
        if status.endswith("1"):
            ins += 1
    # 游标回退60s重叠窗,由唯一约束吸收重复
    await pool.execute(
        "INSERT INTO income_cursors(venue,last_ts_ms,updated_at) VALUES($1,$2,now()) "
        "ON CONFLICT (venue) DO UPDATE SET last_ts_ms=GREATEST(income_cursors.last_ts_ms,$2),updated_at=now()",
        venue, max(since, max_ts - 60_000))
    return ins, ""


async def equity_snapshot(r, pool):
    for v in VENUE_CFG:
        raw = await r.get(f"dcm:account:{v}")
        if not raw:
            continue
        d = json.loads(raw)
        if d.get("ok"):
            # upnl 合计一并落库:对账断言要用 Δ权益−Δ未实现−账单=残差(权益含浮盈,账单只含已实现)
            try:
                upnl = round(sum(float(p.get("upnl") or 0)
                                 for p in (d.get("pos_detail") or {}).values()), 6)
            except Exception:  # noqa: BLE001
                upnl = None
            await pool.execute(
                "INSERT INTO equity_snapshots(venue,equity_usdt,upnl_usdt) VALUES($1,$2,$3)",
                v, float(d.get("equity_usdt") or 0), upnl)


RECON_LOOKBACK_H = int(os.environ.get("DCM_RECON_LOOKBACK_HOURS", "72"))
RECON_SETTLE_H = float(os.environ.get("DCM_RECON_SETTLE_HOURS", "3"))   # 平仓后账单结算窗(bybit walker 滞后)
NEG_STRIKES_KEY = "dcm:carry:neg_strikes"


async def carry_recon(r, pool):
    """P1 逐仓 carry 归因对账:已平 dualperp 仓 → income_records 窗口归因(双腿 venue×symbol),
    拆 funding/pnl/fee/net 落 dualperp_carry_recon;并维护 Redis 连败计数(advisor 降权用)。
    窗口按同币下一仓开仓时间截断,防 GWEI 式高频重开的跨仓串账。
    预期侧:advisor 只路由正 edge,故 net<0 即『实收违约』——无需持久化开仓时 E 值也可判定。"""
    rows = await pool.fetch("""
        SELECT p.id, p.symbol, p.venue_long, p.venue_short, p.notional_usdt,
               p.opened_at, p.closed_at, p.open_gap_bps,
               LEAD(p.opened_at) OVER (PARTITION BY p.symbol ORDER BY p.opened_at) AS next_open
        FROM dualperp_positions p
        WHERE p.closed_at IS NOT NULL AND p.closed_at > now() - ($1 || ' hours')::interval
        ORDER BY p.closed_at""", str(RECON_LOOKBACK_H))
    done = {x["position_id"]: True for x in await pool.fetch(
        "SELECT position_id FROM dualperp_carry_recon WHERE complete")}
    upserts = 0
    for p in rows:
        if done.get(p["id"]):
            continue   # 已定案不重算(历史标签时间局部性)
        bills = await pool.fetch("""
            SELECT itype, coalesce(sum(amount),0) AS amt, count(*) AS n FROM income_records
            WHERE symbol=$1 AND venue = ANY($2::text[])
              AND ts >= $3::timestamptz - interval '5 minutes'
              AND ts <= LEAST($4::timestamptz + interval '35 minutes',
                              COALESCE($5::timestamptz, now()), now())
            GROUP BY itype""",
            p["symbol"], [p["venue_long"], p["venue_short"]],
            p["opened_at"], p["closed_at"], p["next_open"])
        agg = {b["itype"]: float(b["amt"]) for b in bills}
        n = sum(int(b["n"]) for b in bills)
        funding, pnl, fee = agg.get("FUNDING", 0.0), agg.get("PNL", 0.0), agg.get("FEE", 0.0)
        net = round(funding + pnl + fee, 6)
        hold_h = (p["closed_at"] - p["opened_at"]).total_seconds() / 3600.0
        complete = (time.time() - p["closed_at"].timestamp()) > RECON_SETTLE_H * 3600
        await pool.execute("""
            INSERT INTO dualperp_carry_recon(position_id,symbol,venue_long,venue_short,notional_usdt,
                opened_at,closed_at,hold_hours,open_gap_bps,funding_usdt,pnl_usdt,fee_usdt,net_usdt,
                bills_n,complete,updated_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,now())
            ON CONFLICT (position_id) DO UPDATE SET
                funding_usdt=$10, pnl_usdt=$11, fee_usdt=$12, net_usdt=$13,
                bills_n=$14, complete=$15, updated_at=now()""",
            p["id"], p["symbol"], p["venue_long"], p["venue_short"], float(p["notional_usdt"]),
            p["opened_at"], p["closed_at"], round(hold_h, 3),
            float(p["open_gap_bps"]) if p["open_gap_bps"] is not None else None,
            round(funding, 6), round(pnl, 6), round(fee, 6), net, n, complete)
        upserts += 1
    # 连败计数(只采信 complete 行,最近一仓往回数连续 net<0)
    strikes = {}
    for row in await pool.fetch("""
        SELECT symbol, net_usdt, closed_at,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY closed_at DESC) rn
        FROM dualperp_carry_recon WHERE complete ORDER BY symbol, closed_at DESC"""):
        s = strikes.setdefault(row["symbol"], {"strikes": 0, "stopped": False,
                                               "last_close": row["closed_at"].isoformat()})
        if not s["stopped"]:
            if float(row["net_usdt"]) < 0:
                s["strikes"] += 1
            else:
                s["stopped"] = True
    if strikes:
        await r.delete(NEG_STRIKES_KEY)
        payload = {sym: json.dumps({"strikes": v["strikes"], "last_close": v["last_close"]})
                   for sym, v in strikes.items() if v["strikes"] > 0}
        if payload:
            await r.hset(NEG_STRIKES_KEY, mapping=payload)
    return upserts


GUARD_ABS = float(os.environ.get("DCM_RECON_GUARD_ABS_USDT", "5"))
GUARD_PCT = float(os.environ.get("DCM_RECON_GUARD_PCT", "0.02"))
GUARD_WINDOW_H = float(os.environ.get("DCM_RECON_GUARD_WINDOW_H", "24"))
GUARD_COOLDOWN = int(os.environ.get("DCM_RECON_GUARD_COOLDOWN_SEC", "21600"))


async def venue_recon_guard(r, pool, notifier):
    """步⑤ 日度对账断言:逐所 Δ权益 − Δ未实现盈亏 − 账单全类型合计 ≈ 0。
    账单黑洞三连发(bybit 24h窗/bitget buy-sell 分类/bybit cashFlow)全是"HTTP 200 但账本失真",
    只有拿交易所权益这个外部真相对账才能在一天内暴露下一个洞。
    快照对=最新 upnl 非空快照 vs ≥GUARD_WINDOW_H 前最近一张(升级前旧快照无 upnl 自动跳过)。"""
    report = {}
    for v in VENUE_CFG:
        cur = await pool.fetchrow(
            "SELECT equity_usdt, upnl_usdt, ts FROM equity_snapshots "
            "WHERE venue=$1 AND upnl_usdt IS NOT NULL ORDER BY ts DESC LIMIT 1", v)
        if not cur:
            continue
        ref = await pool.fetchrow(
            "SELECT equity_usdt, upnl_usdt, ts FROM equity_snapshots "
            "WHERE venue=$1 AND upnl_usdt IS NOT NULL AND ts <= $2::timestamptz - ($3 || ' hours')::interval "
            "ORDER BY ts DESC LIMIT 1", v, cur["ts"], str(GUARD_WINDOW_H))
        if not ref:
            continue
        bills = float(await pool.fetchval(
            "SELECT coalesce(sum(amount),0) FROM income_records WHERE venue=$1 AND ts>$2 AND ts<=$3",
            v, ref["ts"], cur["ts"]))
        eq_d = float(cur["equity_usdt"]) - float(ref["equity_usdt"])
        up_d = float(cur["upnl_usdt"]) - float(ref["upnl_usdt"])
        residual = round(eq_d - up_d - bills, 2)
        thr = round(max(GUARD_ABS, GUARD_PCT * max(float(cur["equity_usdt"]), 50.0)), 2)
        window_h = round((cur["ts"] - ref["ts"]).total_seconds() / 3600, 1)
        report[v] = {"residual": residual, "eq_delta": round(eq_d, 2), "upnl_delta": round(up_d, 2),
                     "bills": round(bills, 2), "window_h": window_h, "thr": thr}
        if abs(residual) > thr:
            content = (f"近{window_h}h:Δ权益{eq_d:+.2f} − Δ未实现{up_d:+.2f} − 账单{bills:+.2f}"
                       f" = 残差{residual:+.2f}U(阈±{thr})。疑账单缺记:入金未入账/新账单类型落OTHER/"
                       f"分类映射错——按 bybit cashFlow 黑洞流程核 raw 逐类型对账。")
            # 告警(alerts_log+飞书)同门进冷却:缺口是持续态,每轮重发=告警风暴稀释真信号
            if await r.set(f"dcm:pnl:recon_gap:{v}", "1", nx=True, ex=GUARD_COOLDOWN):
                await pool.execute(
                    "INSERT INTO alerts_log(service,akey,level,title,content) VALUES($1,$2,$3,$4,$5)",
                    "pnl-recorder", f"recon_gap:{v}", "warn",
                    f"{v} 账单-权益对账缺口 {residual:+.2f}U", content)
                await asyncio.to_thread(notifier.fire, f"recon_gap:{v}",
                                        f"{v} 账单-权益对账缺口 {residual:+.2f}U", content, "warn")
    if report:
        await r.set("dcm:pnl:recon_guard",
                    json.dumps({"ts": int(time.time()), "venues": report}, ensure_ascii=False),
                    ex=3 * 3600)
    return report


async def summary(pool) -> dict:
    rows = await pool.fetch(
        "SELECT itype, round(sum(amount),4) AS total, "
        "round(sum(amount) FILTER (WHERE ts>date_trunc('day',now())),4) AS today "
        "FROM income_records GROUP BY itype")
    out = {"ts": int(time.time()), "total": {}, "today": {}}
    for r in rows:
        out["total"][r["itype"]] = float(r["total"] or 0)
        out["today"][r["itype"]] = float(r["today"] or 0)
    trade_keys = ("FUNDING", "FEE", "PNL")  # 净额只含交易性收支;TRANSFER/OTHER(划转入金)剔除
    out["net_total"] = round(sum(v for k, v in out["total"].items() if k in trade_keys), 4)
    out["net_today"] = round(sum(v for k, v in out["today"].items() if k in trade_keys), 4)
    return out


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
    active = {v: c for v, c in VENUE_CFG.items() if c.get("key")}
    notifier = Notifier(REDIS_URL, "pnl-recorder", feishu_from_env())
    log.info("pnl-recorder up interval=%ss venues=%s", INTERVAL, list(active))
    last_snap = 0.0
    while True:
        try:
            stats = {}
            async with httpx.AsyncClient(timeout=20) as cli:
                for v, c in active.items():
                    ins, err = await pull_venue(cli, pool, v, c)
                    stats[v] = ins if not err else f"ERR:{err[:60]}"
            if time.time() - last_snap > 3600:
                await equity_snapshot(r, pool)
                last_snap = time.time()
            try:
                rec_n = await carry_recon(r, pool)   # P1 逐仓归因(失败不阻断入账主流程)
            except Exception:
                rec_n = -1
                log.exception("carry recon failed (continuing)")
            try:
                await venue_recon_guard(r, pool, notifier)   # 步⑤ 账单-权益对账断言
            except Exception:
                log.exception("recon guard failed (continuing)")
            s = await summary(pool)
            await r.set("dcm:pnl:summary", json.dumps(s, ensure_ascii=False), ex=INTERVAL * 3)
            await r.set("dcm:hb:pnl-recorder", json.dumps(
                {"service": "pnl-recorder", "ts": int(time.time()), "pid": os.getpid(),
                 "pulled": stats, "net_total": s["net_total"]}, ensure_ascii=False),
                ex=max(INTERVAL * 3, 900))
            log.info("PNL_OK pulled=%s net_total=%s net_today=%s recon=%s",
                     stats, s["net_total"], s["net_today"], rec_n)
        except Exception:
            log.exception("pnl round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
