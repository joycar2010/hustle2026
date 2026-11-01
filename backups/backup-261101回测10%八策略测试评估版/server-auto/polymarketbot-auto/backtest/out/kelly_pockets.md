# Pocket-level Kelly sizing table

generated: 2026-09-18T18:12:24+00:00 | prior m=20 | lambda=0.25 | cap=10% | qualify: n>=50, edge>=0.003

pockets total: 8 | qualified: 2

## Qualified pockets (bet here, fraction = % of equity)

| asset | t_bucket | ask | n | win_rate | p_hat | edge | full Kelly | **fraction** |
|---|---|---|---|---|---|---|---|---|
| BTC | 60-90s | 0.98 | 61 | 1.000 | 0.995 | +0.0136 | 0.735 | **10.00%** |
| ETH | 60-90s | 0.98 | 53 | 1.000 | 0.995 | +0.0129 | 0.706 | **10.00%** |

## Near-miss pockets (positive raw edge, failed qualification)

| asset | t_bucket | ask | n | edge | why rejected |
|---|---|---|---|---|---|
| BTC | 30-60s | 0.98 | 41 | +0.0121 | n<50 |
| ETH | 30-60s | 0.98 | 21 | +0.0089 | n<50 |

## Integration design

1. Runtime reads `kelly_pockets.json`; on each BUY decision the
   (asset, t_bucket, price_bucket) lookup replaces the flat
   `order_risk_fraction` (live logs showed risk=100% per order).
2. fraction = 0 (unqualified pocket) means NO ENTRY under the Kelly
   regime -- entries concentrate where evidence exists.
3. Existing hard limits stay on top: balance reserve, max open
   positions, hourly caps, daily loss circuit, book ask_size clamp.
4. Rollout: shadow first (log would-be fraction next to actual),
   then flip sizing only -- entry rules unchanged in step one.
5. Refresh the table on a schedule (e.g. daily) from the growing
   ledger; PRIOR_STRENGTH keeps thin pockets glued to the quote.
