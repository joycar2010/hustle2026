# P6 — C split_sell bilateral fills + residual closed loop

## Live failure (poly.hustle2026.xyz)

C was minting every window then:

1. Quoting **far above touch** on the weak side (fair+edge lift → e.g. 0.60 vs touch 0.18)
2. Filling **only one leg** (~10 shares)
3. Merging the rest and **redeeming residual into a loss** (~−$0.06 / window × 125)

## Fixes

| Lever | Default | Behavior |
|-------|---------|----------|
| `SPLIT_JOIN_TOUCH` | true | Ask joins best ask (fillable), does not lift to lofty fair |
| `SPLIT_MIN_PAIR_ASK` | 1.01 | Dual quotes only when touch pair clears floor |
| `SPLIT_MIN_ASK_PRICE` | 0.20 | Dual-quote floor (catch-up uses 0.15) |
| `SPLIT_CATCHUP_*` | improve 1 tick / 3s touch | Lagging leg more aggressive after lean |
| `SPLIT_RESIDUAL_FLATTEN` | true | Sell excess inventory at best bid |
| `SPLIT_RESIDUAL_SLA_SEC` | 20 | Flatten + merge if imbalance persists |
| Lean abort | 20s | Flatten residual then merge (no naked redeem) |

## Verify

```bash
pytest -q
python -m btc5m --mode split_sell --once -v
curl -s https://poly.hustle2026.xyz/api/ab | jq .groups.C
```

After deploy, watch for: dual `split_quotes` near touch, `split_flatten` / balanced merge, fewer −$0.06 residual losses.
