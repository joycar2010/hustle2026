"""Forward-only Paper rollout observation. Reads worker snapshots and ledgers in read-only mode."""
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import time


ROOT = Path("/home/ec2-user/polymarketbot-test/state")
PRODUCTS = {
    "btc5m": ("polymarket-test-btc-paper.service", "btc-updown-5m-", 300),
    "btc15m": ("polytest-btc15m-paper.service", "btc-updown-15m-", 900),
    "sol5m": ("polytest-sol5m-paper.service", "sol-updown-5m-", 300),
}
OUT = ROOT / "three-products-observation"
HOUR = 3600
INTERVAL = 600


def write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    os.replace(tmp, path)


def measure(key, start, end):
    unit, prefix, window = PRODUCTS[key]
    effective = json.loads((ROOT / "products" / key / "effective.json").read_text())
    ledger = Path(effective["ledger"]).resolve(strict=True)
    info = subprocess.check_output(
        ["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveState"], text=True
    )
    service = dict(line.split("=", 1) for line in info.splitlines())
    pid_matches = int(service["MainPID"]) == int(effective["pid"]) > 0
    con = sqlite3.connect(ledger.as_uri()+"?mode=ro", uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    try:
        con.execute("begin")
        counts = dict(con.execute(
            "SELECT kind, count(*) FROM events WHERE ts >= ? AND ts < ? GROUP BY kind",
            (start, end)))
        latest = con.execute("SELECT ts, market_slug FROM events WHERE kind='decision' "
                             "AND ts < ? ORDER BY id DESC LIMIT 1", (end,)).fetchone()
        other_series = con.execute(
            "SELECT count(*) FROM events WHERE ts >= ? AND ts < ? AND market_slug <> '' "
            "AND market_slug NOT LIKE ?", (start, end, prefix+"%")).fetchone()[0]
        buys = con.execute("SELECT count(*) FROM events WHERE kind='decision' AND ts>=? "
                           "AND ts<? AND json_extract(payload,'$.action')='BUY'", (start, end)).fetchone()[0]
        fills = con.execute("SELECT count(*), sum(fee_usd), sum(slippage_usd), "
                            "sum(CASE WHEN dry_run IS NOT 1 THEN 1 ELSE 0 END) "
                            "FROM fills WHERE ts>=? AND ts<?", (start, end)).fetchone()
        exit_ms = [row[0] for row in con.execute(
            "SELECT json_extract(payload,'$.exit_latency_ms') FROM events "
            "WHERE kind='stop_exit' AND ts>=? AND ts<?",(start,end)) if row[0] is not None]
        provenance = dict(con.execute("SELECT COALESCE(json_extract(payload,'$.resolution_source'),'unlabelled'), "
                                      "count(*) FROM events WHERE kind='resolve' AND ts>=? AND ts<? GROUP BY 1",
                                      (start,end)))
        positions = list(con.execute("SELECT id, market_slug, closed_ts, size, entry_price, "
                                     "COALESCE(pnl_net_usd,pnl_usd-fee_usd) AS net "
                                     "FROM positions WHERE opened_ts>=? AND opened_ts<?",
                                     (start,end)))
        closed = [p for p in positions if p["closed_ts"] and p["closed_ts"] < end]
        open_positions = [p for p in positions if not p["closed_ts"] or p["closed_ts"] >= end]
        resolved = {row[0] for row in con.execute(
            "SELECT json_extract(payload,'$.position_id') FROM events WHERE kind='resolve' "
            "AND ts >= ? AND ts < ?", (start,end))}
        settle_delays = [p["closed_ts"] - int(p["market_slug"].rsplit("-", 1)[1]) - window
                         for p in closed if p["id"] in resolved and p["market_slug"].startswith(prefix)
                         and p["market_slug"].rsplit("-", 1)[1].isdigit()]
        risk_days = {
            time.strftime("%Y-%m-%d",time.gmtime(row[0]+8*HOUR))
            for row in con.execute("SELECT ts FROM events WHERE kind='risk_block' AND ts>=? AND ts<? "
                                   "AND lower(json_extract(payload,'$.reason')) LIKE '%daily%'",
                                   (start,end))}
        net = [p["net"] for p in closed if p["net"] is not None]
        winners = sum(x > 0 for x in net)
        losers = sum(x < 0 for x in net)
        bankroll = effective.get("paper_bankroll_usd")
        age = round(end-latest["ts"]) if latest else None
        healthy = (service["ActiveState"]=="active" and pid_matches and age is not None
                   and 0 <= age < max(window, 300) and other_series == 0 and not fills[3])
        return {
            "healthy_at_sample": healthy, "pid_matches": pid_matches, "active": service["ActiveState"],
            "last_decision_age_seconds": age, "other_series_events": other_series,
            "event_counts": counts, "buy_signals": buys, "fills": fills[0],
            "entries_per_buy_signal": counts.get("entry",0)/buys if buys else None,
            "non_paper_fills": int(fills[3] or 0), "fees_on_fills_usd": fills[1],
            "slippage_on_fills_usd": fills[2], "positions_closed": len(closed),
            "closed_net_usd": sum(net) if net else None, "unsettled_positions": len(open_positions),
            "closed_net_return_pct_on_paper_capital": 100*sum(net)/bankroll if net and bankroll else None,
            "wins": winners, "losses": losers, "flat_closes": len(net)-winners-losers,
            "win_rate_pct_excluding_flat": 100*winners/(winners+losers) if winners+losers else None,
            "unsettled_shares": sum(p["size"] for p in open_positions),
            "unsettled_cost_usd": sum(p["size"]*p["entry_price"] for p in open_positions),
            "settlement_delay_seconds_median": statistics.median(settle_delays) if settle_delays else None,
            "paper_exit_latency_seconds_median": statistics.median(exit_ms)/1000 if exit_ms else None,
            "risk_block_events": counts.get("risk_block", 0), "resolution_sources":provenance,
            "days_with_daily_risk_block": sorted(risk_days),
        }
    finally:
        con.close()


def sample(start, end):
    result = {}
    for key in PRODUCTS:
        try:
            result[key] = measure(key,start,end)
        except Exception as exc:
            result[key] = {"healthy_at_sample":False, "error":str(exc)}
    return result


def milestone(name,start,end):
    path = OUT / (name+".json")
    if path.exists():
        return
    points = []
    with (OUT/"samples.ndjson").open() as src:
        for line in src:
            if line.strip():
                row = json.loads(line)
                if start <= row["ts"] <= end:
                    points.append(row)
    deltas = [b-a for a,b in zip([start]+[p["ts"] for p in points],
                                  [p["ts"] for p in points]+[end])]
    healthy = {key:sum(p["products"].get(key,False) for p in points) for key in PRODUCTS}
    write(path, {"from":start,"until":end,"samples":len(points),"max_observation_gap_seconds":max(deltas),
                 "healthy_samples":healthy,"metrics":sample(start,end)})


def main():
    OUT.mkdir(mode=0o700,exist_ok=True)
    started = OUT / "schedule.json"
    if not started.exists():
        now = time.time()
        write(started,{"started":now,"smoke_until":now+24*HOUR,"comparison_until":now+72*HOUR})
    schedule=json.loads(started.read_text())
    start, middle, end = [schedule[k] for k in ("started","smoke_until","comparison_until")]
    while not (OUT/"comparison-48h.json").exists():
        now=time.time()
        begin = max(start,now-INTERVAL)
        data=sample(begin,now)
        write(OUT/"latest.json",{"ts":now,"interval_start":begin,"products":data})
        with (OUT/"samples.ndjson").open("a") as out:
            out.write(json.dumps({"ts":now,"products":{k:v["healthy_at_sample"] for k,v in data.items()}})+"\n")
        if now>=middle:
            milestone("smoke-24h",start,middle)
        if now>=end:
            milestone("comparison-48h",middle,end)
            return
        time.sleep(min(INTERVAL,(middle if now<middle else end)-now))


if __name__=="__main__":
    main()
