# P7 — Multi-series rollout (BTC 5m untouched)

## Rule

**BTC 5m behavior and default ledgers are frozen.** Other products are opt-in via `--series` / `SERIES_SLUG` and use separate DBs / overlays.

## Phases

| Phase | Product | Status | Mode | Ledger |
|-------|---------|--------|------|--------|
| 1 baseline | `btc-up-or-down-5m` | **enabled** | late_edge / maker / split_sell | `split_sell_paper.db` etc. |
| 1 | `btc-up-or-down-15m` | **enabled** | split_sell (preferred) | `split_sell_15m_paper.db` |
| 2 | `atp`, `counter-strike` | **enabled** paper | `sports_mm` | `sports_mm_{atp\|cs}_paper.db` |
| 3 | `nba-2026`, `nfl-2026` | scaffold **disabled** | — | — |
| 4 | `dota-2`, `soccer-unl` | scaffold **disabled** | — | — |

## BTC 15m overlays (vs 5m)

- Window 900s, slug `btc-updown-15m-<ts>`
- Longer residual/lean SLA (35s), stop/merge earlier cushions (90s / 30s)
- Same C join-touch + flatten closed loop

```bash
python -m btc5m --series btc15m --mode split_sell --once -v
# or
SERIES_SLUG=btc-up-or-down-15m MODE=split_sell python -m btc5m
```

## Phase 2 sports MM

- `odds_bus.py`: FairQuote + MockSharpProvider (swap real sharp adapter later)
- `event_state.py`: PRE_GAME only quoting
- `sports_discover.py`: mainline only (filters set/map/props)
- `sports_mm.py`: paper bids when `fair − ask ≥ min_edge`

```bash
python -m btc5m products
python -m btc5m --series atp --mode sports_mm --once -v
python -m btc5m --series cs --mode sports_mm --once -v
```

## Module tests

```bash
pytest -q tests/test_p7_products.py tests/test_p6_split.py tests/test_p5.py
pytest -q   # full suite — BTC 5m tests must still pass
```

## Do not

- Point production A/B/C 5m processes at `--series btc15m` (separate systemd unit if deployed)
- Enable NBA/NFL/Dota/soccer until phase gates are lifted in `products.py`

## P7.1 remediation (dashboard audit)

| Issue | Fix |
|-------|-----|
| ATP shown as “no eligible market” while day −$57 | Heartbeat `status=risk_blocked`; sports daily loss limit separate (`SPORTS_DAILY_LOSS_LIMIT_USD`) |
| CS discover empty | Gamma `ascending=false`, higher limit, drop far-past LIVE backlog |
| Map lines treated as mainline | Prop regex catches `game1` / `Map 1` / spreads |
| MockSharp noise trading | Default `SPORTS_QUOTE_ON_MOCK=0`; status `mock odds (no quote)` until `ODDS_API_KEY` |
| B empty sessions inflate KPIs | `/api/ab` + products expose `filled_sessions` / `empty_closed_sessions` |
| C +$34 misread as pair edge | `/api/split/quality` → `edge_attribution` (residual winner/loser) |
| LIVE sports zombies | `_sweep_stale_sessions` closes `LIVE_ABORT` / `EXPIRED_EMPTY` |
| 5m/15m/ATP/CS heartbeat clobber | Modes `split_sell_15m`, `sports_mm_atp`, `sports_mm_cs` |
