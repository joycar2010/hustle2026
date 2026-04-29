"""Check MT5 bridge deals for cq456"""
import asyncio, httpx, os, sys
from datetime import datetime, timezone, timedelta

async def main():
    bridge_host = "http://172.31.14.113"
    api_key = os.getenv("MT5_API_KEY", "")
    headers = {"X-Api-Key": api_key} if api_key else {}

    for port in [8003, 8023]:
        print(f"\n=== Bridge port {port} ===")
        for days in [2, 5, 30]:
            async with httpx.AsyncClient(timeout=15.0) as http:
                try:
                    resp = await http.get(f"{bridge_host}:{port}/mt5/history/deals", headers=headers, params={"days": days})
                    all_deals = resp.json().get("deals", [])
                    print(f"  days={days}: total deals={len(all_deals)}")

                    target_syms = {"XAUUSD+", "XAUUSD", "XAGUSD", "XTIUSD", "XNGUSD", "XBRUSD"}
                    # Beijing April 30 = UTC April 29 16:00 ~ April 30 15:59:59
                    start_ts = datetime(2026, 4, 29, 16, 0, 0, tzinfo=timezone.utc).timestamp()
                    end_ts = datetime(2026, 4, 30, 15, 59, 59, tzinfo=timezone.utc).timestamp()

                    today_close = [d for d in all_deals if d.get("symbol") in target_syms and start_ts <= d.get("time", 0) <= end_ts and d.get("entry") == 1]
                    today_all = [d for d in all_deals if start_ts <= d.get("time", 0) <= end_ts]
                    today_sym = [d for d in all_deals if d.get("symbol") in target_syms and start_ts <= d.get("time", 0) <= end_ts]

                    print(f"    Apr 30 Beijing: all={len(today_all)}, target_sym={len(today_sym)}, close_only={len(today_close)}")

                    if today_sym:
                        tp = sum(float(d.get("profit", 0)) for d in today_close)
                        ts = sum(float(d.get("swap", 0)) for d in today_close)
                        print(f"    Close profit={tp:.2f}, swap={ts:.2f}")

                    # Show last 15 deals
                    if days == 5:
                        print(f"    Last 15 deals:")
                        for d in all_deals[-15:]:
                            dt = datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc) + timedelta(hours=8)
                            print(f"      {dt.strftime('%m-%d %H:%M:%S')} sym={d.get('symbol',''):12s} entry={d.get('entry',0)} profit={d.get('profit',0):>10.2f} swap={d.get('swap',0):>8.2f} vol={d.get('volume',0)}")
                except Exception as e:
                    print(f"  days={days}: ERROR: {e}")

asyncio.run(main())
