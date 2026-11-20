# P0 A — price-band cut + faster bucket fuse

Live A (`poly.hustle2026.xyz`) showed 28/29 DOWN entries clustered at 0.75–0.83;
bucket `[0.80,0.85)` WR ≈ 57% vs ~85% breakeven (n=7, −$18) while
`BUCKET_MIN_SAMPLES=8` had not yet banned it.

## Changes (defaults)

| Knob | Was | Now |
|------|-----|-----|
| `MAX_ENTRY_PRICE` | 0.88 | **0.79** |
| `LATE_EDGE_EDGE_SAFETY` | 1.25 | **1.5** |
| `LEAD_EDGE_MARGIN` | 0.03 | **0.05** |
| `BUCKET_MIN_SAMPLES` | 8 | **5** |
| `BUCKET_WR_BUFFER` | 0.02 | **0.03** |

Plus `FORCE_BAN_BUCKETS = {(0.80, 0.85)}` in `calibration.py` so the toxic band
stays banned even with n < min_samples / if `MAX_ENTRY` is raised later.

Redeploy upserts these into remote `.env` via `scripts/deploy_polydex.sh`.
