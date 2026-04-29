"""Debug: trace cq456 today PnL for Beijing April 30"""
import asyncio, os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, ".")

def _beijing_date_to_utc_ms(date_str, end_of_day=False):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    utc_dt = dt - timedelta(hours=8)
    return int(utc_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

def _utc_ms_to_beijing_date(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    beijing = dt + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d")

USER_ID = "439b5a1f-b938-4548-ba31-1338a0c326a2"

async def main():
    from app.core.database import AsyncSessionLocal
    from app.core.proxy_utils import build_proxy_url
    from app.services.binance_client import BinanceFuturesClient
    from app.models.mt5_client import MT5Client
    from sqlalchemy import text, select
    import httpx

    # Beijing April 30 = UTC April 29 16:00 ~ April 30 15:59:59
    today = "2026-04-30"
    start_ms = _beijing_date_to_utc_ms(today)
    end_ms = _beijing_date_to_utc_ms(today, end_of_day=True)

    print(f"=== cq456 Today PnL Debug (Beijing {today}) ===")
    print(f"UTC range: {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)} ~ {datetime.fromtimestamp(end_ms/1000, tz=timezone.utc)}")

    totals = {"binance_rpnl": 0, "binance_ffee": 0, "mt5_profit": 0, "mt5_swap": 0, "mt5_comm": 0}

    async with AsyncSessionLocal() as db:
        # === BINANCE ===
        r = await db.execute(text(
            "SELECT account_id, account_name, api_key, api_secret, proxy_config "
            "FROM accounts WHERE user_id = :uid AND platform_id = 1"
        ), {"uid": USER_ID})
        bn_acc = r.first()
        if bn_acc:
            print(f"\n--- Binance: {bn_acc.account_name} ---")
            proxy = build_proxy_url(bn_acc.proxy_config)
            client = BinanceFuturesClient(bn_acc.api_key, bn_acc.api_secret, proxy_url=proxy)
            try:
                pnl_recs = await client.get_income(income_type="REALIZED_PNL", start_time=start_ms, end_time=end_ms, limit=1000)
                total_rpnl = sum(float(r.get("income", 0)) for r in pnl_recs)
                totals["binance_rpnl"] = total_rpnl
                print(f"  REALIZED_PNL: {len(pnl_recs)} records, total={total_rpnl:.4f} USDT")
                for r in pnl_recs:
                    dt_full = datetime.fromtimestamp(int(r["time"])/1000, tz=timezone.utc) + timedelta(hours=8)
                    print(f"    {dt_full.strftime('%Y-%m-%d %H:%M:%S')} {r.get('symbol',''):12s} {float(r.get('income',0)):>12.4f}")

                fee_recs = await client.get_income(income_type="FUNDING_FEE", start_time=start_ms, end_time=end_ms, limit=1000)
                total_ffee = sum(float(r.get("income", 0)) for r in fee_recs)
                totals["binance_ffee"] = total_ffee
                print(f"  FUNDING_FEE: {len(fee_recs)} records, total={total_ffee:.4f} USDT")
                for r in fee_recs:
                    dt_full = datetime.fromtimestamp(int(r["time"])/1000, tz=timezone.utc) + timedelta(hours=8)
                    print(f"    {dt_full.strftime('%Y-%m-%d %H:%M:%S')} {r.get('symbol',''):12s} {float(r.get('income',0)):>12.4f}")

                # Also check COMMISSION for completeness
                comm_recs = await client.get_income(income_type="COMMISSION", start_time=start_ms, end_time=end_ms, limit=1000)
                total_comm = sum(float(r.get("income", 0)) for r in comm_recs)
                print(f"  COMMISSION: {len(comm_recs)} records, total={total_comm:.4f} USDT")
            finally:
                await client.close()

        # === MT5 accounts ===
        br = await db.execute(text(
            "SELECT DISTINCT account_b_id FROM user_pair_accounts WHERE user_id = :uid AND account_b_id IS NOT NULL"
        ), {"uid": USER_ID})
        bound_b_ids = {str(row[0]) for row in br.fetchall()}

        sr = await db.execute(text(
            "SELECT DISTINCT sb.symbol FROM hedging_pairs hp "
            "JOIN platform_symbols sb ON hp.symbol_b_id = sb.id WHERE hp.is_active = true"
        ))
        target_syms = {row[0] for row in sr.fetchall()}

        r_mt5 = await db.execute(text(
            "SELECT account_id, account_name, platform_id "
            "FROM accounts WHERE user_id = :uid AND is_mt5_account = true"
        ), {"uid": USER_ID})
        mt5_accounts = r_mt5.fetchall()

        for acc in mt5_accounts:
            acc_id_str = str(acc.account_id)
            if acc_id_str not in bound_b_ids:
                continue

            print(f"\n--- MT5: {acc.account_name} (platform={acc.platform_id}) ---")
            pr = await db.execute(
                select(MT5Client.bridge_service_port).where(
                    MT5Client.account_id == acc.account_id,
                    MT5Client.is_active == True,
                    MT5Client.is_system_service == False,
                    MT5Client.bridge_service_port.isnot(None),
                ).limit(1)
            )
            port = pr.scalar_one_or_none()
            if not port:
                print("  No bridge port")
                continue

            bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
            api_key = os.getenv("MT5_API_KEY", "")
            headers = {"X-Api-Key": api_key} if api_key else {}

            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(f"{bridge_host}:{port}/mt5/history/deals", headers=headers, params={"days": 2})
                all_deals = resp.json().get("deals", [])

            start_ts = start_ms / 1000
            end_ts = end_ms / 1000
            today_deals = [
                d for d in all_deals
                if d.get("symbol") in target_syms
                and start_ts <= d.get("time", 0) <= end_ts
                and d.get("entry", 0) == 1
            ]
            tp = sum(float(d.get("profit", 0)) for d in today_deals)
            ts_val = sum(float(d.get("swap", 0)) for d in today_deals)
            tc = sum(float(d.get("commission", 0)) for d in today_deals)
            totals["mt5_profit"] += tp
            totals["mt5_swap"] += ts_val
            totals["mt5_comm"] += tc
            print(f"  Today closed deals: {len(today_deals)}, profit={tp:.4f}, swap={ts_val:.4f}, comm={tc:.4f}")
            for d in today_deals:
                dt_full = datetime.fromtimestamp(int(d["time"]), tz=timezone.utc) + timedelta(hours=8)
                print(f"    {dt_full.strftime('%Y-%m-%d %H:%M:%S')} {d.get('symbol',''):12s} vol={d.get('volume',0):>6} profit={float(d.get('profit',0)):>10.2f} swap={float(d.get('swap',0)):>8.2f} comm={float(d.get('commission',0)):>8.2f}")

    # Also check: what does the actual API return (from log)?
    # The API was called with range 2026-01-30~2026-04-30
    # Let me also compute April 29 Beijing for comparison
    print("\n--- Also checking Beijing April 29 for comparison ---")
    apr29_start = _beijing_date_to_utc_ms("2026-04-29")
    apr29_end = _beijing_date_to_utc_ms("2026-04-29", end_of_day=True)
    async with AsyncSessionLocal() as db:
        r = await db.execute(text(
            "SELECT account_id, api_key, api_secret, proxy_config "
            "FROM accounts WHERE user_id = :uid AND platform_id = 1"
        ), {"uid": USER_ID})
        bn_acc = r.first()
        if bn_acc:
            proxy = build_proxy_url(bn_acc.proxy_config)
            client = BinanceFuturesClient(bn_acc.api_key, bn_acc.api_secret, proxy_url=proxy)
            try:
                pnl_recs = await client.get_income(income_type="REALIZED_PNL", start_time=apr29_start, end_time=apr29_end, limit=1000)
                rpnl29 = sum(float(r.get("income", 0)) for r in pnl_recs)
                fee_recs = await client.get_income(income_type="FUNDING_FEE", start_time=apr29_start, end_time=apr29_end, limit=1000)
                ffee29 = sum(float(r.get("income", 0)) for r in fee_recs)
                print(f"  April 29 Beijing: RPNL={rpnl29:.4f}, FFEE={ffee29:.4f}, net={rpnl29+ffee29:.4f}")
            finally:
                await client.close()

    # === SUMMARY ===
    print("\n" + "="*60)
    print(f"TODAY (Beijing {today}) PNL BREAKDOWN:")
    print(f"  Binance REALIZED_PNL:  {totals['binance_rpnl']:>12.4f}")
    print(f"  Binance FUNDING_FEE:   {totals['binance_ffee']:>12.4f}")
    print(f"  MT5 profit:            {totals['mt5_profit']:>12.4f}")
    print(f"  MT5 swap:              {totals['mt5_swap']:>12.4f}")
    print(f"  MT5 commission:        {totals['mt5_comm']:>12.4f}")
    net = totals['binance_rpnl'] + totals['binance_ffee'] + totals['mt5_profit'] + totals['mt5_swap'] + totals['mt5_comm']
    print(f"  ---")
    print(f"  NET PNL (net_pnl):     {net:>12.4f}")
    print("="*60)

asyncio.run(main())
