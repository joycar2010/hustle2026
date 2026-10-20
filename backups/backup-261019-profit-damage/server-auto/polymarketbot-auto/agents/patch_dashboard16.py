"""In-place patch #16: wire the external feeds into the dashboard.

- poll_kalshi_weather_loop: Kalshi high-temp brackets -> ensemble signal ->
  existing paper entry hook; settlements polled into resolutions.  Env gate
  KALSHI_WEATHER_ENABLED (default on), 180s cadence, error-keyed like other
  pollers.
- SportsPaperService now receives the bookmaker-consensus data source when
  ODDS_API_KEY is configured (market-implied fallback otherwise).

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard16.py <path>
"""
from __future__ import annotations

import sys

LOOP = '''async def poll_kalshi_weather_loop():
    """Kalshi daily high-temp brackets vs the Open-Meteo ensemble model.

    Reference prices only -- paper entries land in OUR ledger through the
    same hook the Polymarket weather branch uses; settlements are polled
    from Kalshi's public API into the local resolutions table."""
    if os.environ.get("KALSHI_WEATHER_ENABLED", "true").strip().lower() not in (
            "1", "true", "yes", "on"):
        return
    from bot.feeds.kalshi_weather import (
        fetch_kalshi_weather_markets,
        resolve_kalshi_settlements,
    )
    while True:
        try:
            markets = await asyncio.to_thread(fetch_kalshi_weather_markets)
            for market in markets:
                try:
                    forecast = await asyncio.to_thread(
                        fetch_ensemble_forecast, cfg, market.city_key, market.target_date)
                except Exception:
                    continue
                signal = build_signal(cfg, market, forecast)
                _maybe_weather_paper_entry(market, signal)
            settled = await asyncio.to_thread(resolve_kalshi_settlements)
            _state["kalshi_weather"] = {
                "markets": len(markets), "settled_new": settled,
                "ts": time.time(),
            }
            _state["errors"].pop("kalshi_weather", None)
        except Exception as exc:
            _state["errors"]["kalshi_weather"] = str(exc)
        await asyncio.sleep(180.0)


async def poll_bot_running_loop():'''

SPORTS_SRC = '''def _build_sports_data_source():
    """Bookmaker-consensus probabilities when ODDS_API_KEY is set; None keeps
    the market-implied fallback (edge stays ~0, gate stays quiet)."""
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    switch = os.environ.get("SPORTS_ODDS_SOURCE", "the-odds-api").strip().lower()
    if not api_key or switch in ("off", "0", "false", "none"):
        return None
    try:
        from bot.feeds.odds_consensus import OddsConsensusSource
        return OddsConsensusSource(api_key=api_key)
    except Exception:
        return None


_sports_service = SportsPaperService(cfg, data_source=_build_sports_data_source())'''

E = [
    ("async def poll_bot_running_loop():", LOOP),
    ("_sports_service = SportsPaperService(cfg)", SPORTS_SRC),
    ("    asyncio.create_task(poll_sports_loop())",
     "    asyncio.create_task(poll_sports_loop())\n"
     "    asyncio.create_task(poll_kalshi_weather_loop())"),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "poll_kalshi_weather_loop" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1)")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
