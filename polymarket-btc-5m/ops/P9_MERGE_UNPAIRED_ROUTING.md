# P9 — C merge accounting · B unpaired abort · eth/sol routing

## C · split_sell merge cash

**Bug:** full merge (`merged=mint`, sells=0) settled as `net ≈ −mint` after restart because `merge_proceeds` lived only in memory.

**Fix:**
- Persist cash legs via `Store.update_split_cash` on merge / sell / flatten
- Hydrate merge/sell/redeem from DB in `_ensure_session` and `_resolve_open` (infer merge if inv cleared)
- `repair_split_merge_accounting(db)` + CLI: `python -m btc5m repair-split [--dry-run]`

After deploy, run repair on prod C ledger (e.g. session 391).

## B · unpaired abort

**Bug:** one-sided fill → pair-complete flatten → still held residual to settlement (`pair_complete ≈ 1/75`).

**Fix:**
- Track `MakerState.paired_peak`
- `MAKER_CLOSE_ON_UNPAIRED_FLATTEN=true` (default): after flatten, if never paired → close `winner=UNPAIRED_ABORT`, PnL = flatten only
- Default `MAKER_PAIR_COMPLETE_SEC` **20 → 12**

## eth5m / sol5m dashboard

**Bug:** `/api/positions|events?group=eth5m|sol5m` could fall through to A's `paper.db`; product KPIs used maker-session report on positions DBs.

**Fix:**
- `_resolve_group_db` — product keys before A/B/C
- `late_edge_activity_report` for eth/sol product payload
- Slug-prefix filter (`eth-updown` / `sol-updown`) as belt-and-suspenders
