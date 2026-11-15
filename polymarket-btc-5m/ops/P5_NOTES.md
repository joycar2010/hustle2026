# P5a / P5b — C split_sell + B1 hardening

## Why

Live PAPER on poly.hustle2026.xyz showed:

- **A1** still fee-hostile taker (research-only).
- **B1** headline PnL hid **0 paired sessions**, cheap lottery inventory ($0.01–$0.13), and residual gambling.
- **C** existed in code but was **not deployed**.

## P5b — maker (group B)

| Gate | Default | Behavior |
|------|---------|----------|
| `MAKER_MIN_BID_PRICE` | 0.20 | No bids / fills below floor |
| `MAKER_PAIR_COMPLETE_SEC` | 20 | After one-sided fill, if missing leg not filled → early flatten |
| `MAKER_EARLY_FLATTEN` | true | Enable mid-window flatten on SLA breach |
| `MAKER_ZERO_FILL_KILL_SEC` | 90 | If still zero fills when `t_left ≤ 90` → stop quoting |
| `MAKER_PAIR_COST_MAX` / `MAKER_PAIR_PROFIT_MIN` | 0.96 / 0.03 | Tighter pair cap |

Missing-leg-only quoting (P0/P1) remains.

## P5a — split_sell (group C)

| Gate | Default | Behavior |
|------|---------|----------|
| `SPLIT_MIN_ASK_PRICE` | 0.35 | Floor on each ask |
| `SPLIT_MIN_PAIR_ASK` | 1.02 | When quoting both legs, require sum ≥ 1.02 |
| `SPLIT_LEAN_ABORT_SEC` | 25 | Lean clamp lasting too long → stop asks + merge remaining pairs |

Ledger: `data/split_sell_paper.db` · dashboard **C** · `/api/split/quality`.

## Run / deploy

```bash
python -m btc5m --mode split_sell
bash scripts/run_split_sell_paper.sh
PEM=... HOST=ec2-user@... bash scripts/deploy_polydex.sh   # enables systemd C
```

## Verify

```bash
python -m btc5m report --mode split_sell
curl -s https://poly.hustle2026.xyz/api/ab | jq .groups.C
curl -s https://poly.hustle2026.xyz/api/split/quality
```
