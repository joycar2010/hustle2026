# P1 / P2 — strategy structure + observability (v1.3)

## P1

### Late edge
- Rolling **entry-price bucket WR circuit breaker** (`btc5m/calibration.py`)
  - If lookback WR < fee-aware required WR (min samples), ban that bucket
  - Wired into `decide(..., db_path=...)`
- **Multi-venue median** spot (OKX / Coinbase / Kraken) + **consensus** gate
  - `SIGNAL_REQUIRE_CONSENSUS=true`, `SIGNAL_MIN_VENUES=2`
- Paper entries continue to record **taker fee** on every fill (`fee_usd` / `pnl_net_usd`)

### Maker
- **Pair-profit first**: effective cap = `min(MAKER_PAIR_COST_MAX, 1 - MAKER_PAIR_PROFIT_MIN)`
- Missing-leg-only quoting + imbalance hard cap (unchanged from P0)
- **Fill quality** counters: touch / crossed / flatten / skipped_imbalance

## P2

- `python -m btc5m report` now prints:
  - entry-price buckets + BAN flags
  - maker paired gross vs residual / flatten
  - fill quality (crossed rate)
  - friction stress (1-tick slip + fee curve) for late_edge DBs
- `python -m btc5m heartbeat` / `/api/heartbeat` — stale process alerts
- `python -m btc5m stress` — standalone friction replay
- Dashboard: `/api/calibration`, `/api/maker/quality`, heartbeat in `/api/health` + `/api/state`

## Commands

```bash
python -m btc5m report --mode late_edge
python -m btc5m report --mode maker
python -m btc5m heartbeat
python -m btc5m stress --slip-ticks 1 --fee-mult 1
python -m btc5m dashboard
```
