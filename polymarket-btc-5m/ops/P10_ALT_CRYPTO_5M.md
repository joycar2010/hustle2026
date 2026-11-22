# P10 — Alt crypto 5m paper scaffolds (SOL-like late_edge)

## Scope

Paper-only products cloning **SOL5m late_edge** gates with **bp→USD scaling**:

| Key | Series | Ledger | Notes |
|-----|--------|--------|-------|
| `xrp5m` | `xrp-up-or-down-5m` | `paper_xrp5m.db` | First pilot (best liquidity among alts) |
| `bnb5m` | `bnb-up-or-down-5m` | `paper_bnb5m.db` | Tighter entry; `price_hosts=okx,binance` |
| `doge5m` | `doge-up-or-down-5m` | `paper_doge5m.db` | Thin book → stricter bp/entry |
| `hype5m` | `hype-up-or-down-5m` | `paper_hype5m.db` | Thinnest; okx+binance |

**Not in scope:** BTC Bitcoin 永续 / 50x perps; overwriting BTC5m A/B/C defaults.

## SOL template (bp)

At SOL spot ≈ $70: `up_min_delta≈0.12` (~17.1 bp), `down_max_delta≈−0.20` (~28.5 bp),
`lead_table_enabled=False`, `max_entry≈0.78`, gap cap `0.76`.

Alt products use `_sol_like_late_edge(spot_ref=…)` so absolute $Δ tracks coin price.

## Run

```bash
python -m btc5m --series xrp5m --mode late_edge --once -v
python -m btc5m --series bnb5m --mode late_edge --once -v
python -m btc5m --series doge5m --mode late_edge --once -v
python -m btc5m --series hype5m --mode late_edge --once -v
```

Dashboard: `/api/positions?group=xrp5m` → `paper_xrp5m.db` (same for bnb/doge/hype).

## Acceptance before live

1. XRP ≥50 paper fills with UP/DOWN mix audit (SOL live tape was DOWN-heavy)
2. Spread / depth watch on DOGE/HYPE
3. Heartbeat `late_edge_xrp5m` (etc.) fresh on deploy host
