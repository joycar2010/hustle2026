# P0 Fix Notes — A/B Paper loss remediation

## Root cause (from poly.hustle2026.xyz API)

- **A late_edge**: WR 84.6% but expectancy negative because entries at 0.91–0.95 win ~$0.5–$2 and lose ~$9.5. Bucket ≥0.90 alone ≈ −$28.
- **B maker**: 0/9 wins, −$91.6. Pattern matches one-sided inventory held to resolution; crossed paper fills + imbalance up to 20; process stale ~16h.

## Code changes in 1.2.0

### A
- `MAX_ENTRY_PRICE=0.88`
- `LATE_EDGE_HARD_BAN_PRICE=0.90`
- `MIN_NET_EDGE=0.08`, `CONFIRM_CHECKS=3`
- Stronger delta ±25
- Fee-aware entry still recorded on fills

### B
- Quote only the missing leg after any imbalance
- `MAKER_MAX_IMBALANCE_SHARES=10`
- Crossed fills off by default
- Flatten unpaired residual at best bid before resolution
- Persist `flatten_pnl_usd`

### Dashboard
- `python -m btc5m dashboard` serves `/api/ab` and `/api/positions?group=A|B` from **separate** DBs

## Deploy

SSH from an allowlisted IP:

```bash
PEM=/path/HustleNew.pem HOST=ec2-user@18.179.50.168 \
  bash scripts/deploy_polydex.sh
```

Cloud Agent egress IPs that need SG:22 open: see deploy chat.
