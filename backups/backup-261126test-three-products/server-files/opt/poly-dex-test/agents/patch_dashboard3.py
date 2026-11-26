"""In-place patch #3: expose paper/live KPI lanes side by side (mode_split).

The UI must LABEL which lane a number belongs to instead of silently
switching meaning with bot_mode.  Adds _mode_split() -- today's realized
summary plus open exposure for BOTH dry_run lanes -- and wires it into
/api/state.  Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard3.py <path>
"""
from __future__ import annotations

import sys

HELPER = '''

def _mode_split() -> dict[str, Any]:
    """Paper and live KPI families side by side so the UI can label lanes.

    balance_pusd stays chain-truth and mode-free; this block covers realized
    PnL (today), win/loss, pending and open exposure per lane."""
    paper = dict(realized_pnl_summary_today(True))
    live = dict(realized_pnl_summary_today(False))
    n, usd = _paper_open_stats()
    paper.update(open_count=n, open_value_usd=usd)
    live_positions = _filter_active_positions(_state.get("positions") or [])
    live_value = 0.0
    for item in live_positions:
        try:
            live_value += float(item.get("size") or 0) * float(item.get("curPrice") or 0)
        except (TypeError, ValueError):
            continue
    live.update(open_count=len(live_positions), open_value_usd=round(live_value, 4))
    return {"paper": paper, "live": live}
'''

ANCHOR_AFTER = '    return _paper_open_cache["n"], _paper_open_cache["usd"]'
STATE_OLD = '        "pnl": pnl,\n        "slow_loop": _slow_loop_extras(),'
STATE_NEW = ('        "pnl": pnl,\n        "mode_split": _mode_split(),\n'
             '        "slow_loop": _slow_loop_extras(),')


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_mode_split" in src:
        print("already patched; nothing to do")
        return 0
    for name, a in (("helper-pos", ANCHOR_AFTER), ("state-line", STATE_OLD)):
        if src.count(a) != 1:
            print(f"ABORT: anchor {name} count={src.count(a)} (need 1)")
            return 2
    src = src.replace(ANCHOR_AFTER, ANCHOR_AFTER + HELPER, 1)
    src = src.replace(STATE_OLD, STATE_NEW, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
