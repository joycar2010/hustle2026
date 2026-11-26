# P3 / P4 — TWAP lead model + split-sell (v1.4)

## P3

| Piece | Module | Behavior |
|-------|--------|----------|
| Lead-hold WR table | `lead_table.py` | 34,559-window empirical hold rates by lead bp × elapsed |
| Projected TWAP | `twap.py` | Final-minute blend of spot buffer; venue proxy until PolyBolt auth |
| Opening gap | `strategy.py` | First 60s: trade if gap≥5bp and ask cheap vs hold WR |
| Late edge | `strategy.py` | Enter only when `hold_wr − (ask+fee+margin) > 0` |

## P4

| Piece | Module | Behavior |
|-------|--------|----------|
| `MODE=split_sell` | `split_sell.py` | Paper mint N sets → post-only asks → lean clamp → merge → redeem |
| Fast book | `ws_book.py` | 150ms TTL cache (REST); websocket-client hook documented |
| Ledger | `split_sell_paper.db` | Dashboard group **C** |
| Rebate | `SPLIT_REBATE_BPS` | Default 42 bps of sold notional (estimate) |

Live CTF mint/merge/redeem and real CLOB WS cancel/replace are **not** armed.

## Commands

```bash
python -m btc5m --mode split_sell
python -m btc5m --mode late_edge --once -v
python -m btc5m report --mode split_sell
python -m btc5m heartbeat
```
