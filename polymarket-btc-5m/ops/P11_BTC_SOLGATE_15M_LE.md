# P11 — BTC5m A′ solgate half + BTC15m late_edge paper

## Goal

Port **SOL5m late_edge structure** (stricter bp / entry / gap) onto BTC **without** mutating frozen BTC5m A defaults or BTC15m C (`split_sell`).

## Products

| Key | Series | Mode | Ledger | Notes |
|-----|--------|------|--------|-------|
| `btc5m_solgate` | `btc-up-or-down-5m` | late_edge | `paper_btc5m_solgate.db` | A′ shadow; **keep** `lead_table_enabled` |
| `btc15m_le` | `btc-up-or-down-15m` | late_edge | `paper_btc15m.db` | Parallel to C; time-stretched windows |
| `btc15m` + `--mode late_edge` | same | remaps → `btc15m_le` | same | CLI convenience |

## Half-tier gates (`_btc_half_solgate`)

Vs SOL full (~17.1 / 28.5 bp), half mid-band:

- Δ: **10 bp UP / 16 bp DOWN** @ `spot_ref=90000` → ≈ **+$90 / −$144**
- lead: 2.5 / 2.0 / 3.5 bp
- opening gap: 6.5 bp; max entry **0.78** / gap cap **0.76**
- `lead_table_enabled=True` (BTC hold table retained)

### 15m stretch (`btc15m_le`)

- `entry_window_sec=120`, `min_t_remaining_sec=30`
- `opening_gap_window_sec=120`, `confirm_checks=4`

## Run

```bash
python -m btc5m --series btc5m_solgate --mode late_edge --once -v
python -m btc5m --series btc15m --mode late_edge --once -v
# or explicit:
python -m btc5m --series btc15m_le --mode late_edge --once -v
```

Baseline A (`paper.db`) and C (`split_sell_*`) are unchanged.

## Acceptance (paper)

1. **btc5m_solgate**: ≥50 fills vs baseline A on WR, $/fill, daily fill count  
2. **btc15m_le**: ≥30 fills; stop if EV≤0 or WR≪SOL  
3. Heartbeats `late_edge_btc5m_solgate` / `late_edge_btc15m_le` fresh on host  
4. No change to BTC5m A/B/C default env when series omitted  

## Explicitly out of scope

- Full-tier (17.1/28.5 bp) shadow  
- Switching default A or replacing BTC15m C  
- Live trading  
