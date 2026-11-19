# P8 — ETH/SOL late_edge + OddsAPI sports enablement

## Rule

**BTC 5m A/B/C defaults and ledgers stay frozen.** New products are opt-in via `--series`.

## What landed

| # | Product | Mode | Ledger | Notes |
|---|---------|------|--------|-------|
| 1 | `eth5m` | `late_edge` | `paper_eth5m.db` | Scaled Δ (±$0.80), `crypto_asset=eth` |
| 2 | `sol5m` | `late_edge` | `paper_sol5m.db` | Stricter lead/gap bp, Δ ±$0.15 |
| 3 | `nba` / `nfl` | `sports_mm` | `sports_mm_{nba\|nfl}_paper.db` | The Odds API h2h → fair MM |
| 4 | `dota` / `soccer_unl` | `sports_mm` | `sports_mm_*_paper.db` | Mainline-only; live/props filtered |

## Odds API

- Env: `ODDS_API_KEY` (never commit). Optional `ODDS_SPORT_KEYS` override.
- When key is set, bus uses `OddsApiProvider` only (no silent mock fallthrough).
- Default `SPORTS_QUOTE_ON_MOCK=0`; sessions open only when a non-mock fair quote matches.
- NBA → `basketball_nba`; NFL → `americanfootball_nfl`.
- Soccer-UNL: best-effort UEFA/EPL/… keys (Nations League itself not listed on OddsAPI).
- Dota: no OddsAPI sport on this key → discover runs, quotes stay empty until a real adapter exists.

## Commands

```bash
python -m btc5m products
python -m btc5m --series eth5m --mode late_edge --once -v
python -m btc5m --series sol5m --mode late_edge --once -v
ODDS_API_KEY=… python -m btc5m --series nba --mode sports_mm --once -v
ODDS_API_KEY=… python -m btc5m --series nfl --mode sports_mm --once -v
python -m btc5m --series dota --mode sports_mm --once -v
python -m btc5m --series soccer_unl --mode sports_mm --once -v
pytest -q
```

## Do not

- Point BTC 5m production units at eth/sol/nba series
- Enable `SPORTS_QUOTE_ON_MOCK=1` in production paper
- Treat soccer-unl starting-XI / player props as mainline (prop filter drops them)
- Commit `.env` or paste live keys into git
