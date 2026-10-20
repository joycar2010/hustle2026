"""In-place patch #13: unify the capital base per lane.

The UI's return%% and the daily-loss tile divided PAPER results by the CHAIN
balance ($28.42) while the worker's own risk gate uses paper_equity_usd
($100).  Each mode_split lane now carries its authoritative
`capital_base_usd` (paper = cfg.paper_equity_usd; live = chain balance +
live open value), and the dashboard-side _risk_state display uses the same
paper base as the worker gate.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard13.py <path>
"""
from __future__ import annotations

import sys

E = [
    # 1) capital base on both lanes (inside _mode_split, before by_asset attach)
    ('    by_asset = _asset_lane_pnl(float(paper.get("period_start_ts") or 0.0))',
     '    paper["capital_base_usd"] = round(float(getattr(cfg, "paper_equity_usd", 100.0)), 2)\n'
     '    live["capital_base_usd"] = round(float(_state.get("balance_pusd") or 0.0) + live_value, 4)\n'
     '    by_asset = _asset_lane_pnl(float(paper.get("period_start_ts") or 0.0))'),
    # 2) _risk_state display equity aligned with the worker gate in paper mode
    ('    balance = _state.get("balance_pusd")\n'
     '    value = _state.get("value_usd") or 0.0\n'
     '    equity = (balance if balance is not None else cfg.paper_equity_usd) + value',
     '    if _state.get("bot_mode") != "live":\n'
     '        # Match the worker gate: paper capital + paper open exposure.\n'
     '        equity = float(getattr(cfg, "paper_equity_usd", 100.0)) + _paper_open_stats()[1]\n'
     '    else:\n'
     '        balance = _state.get("balance_pusd")\n'
     '        value = _state.get("value_usd") or 0.0\n'
     '        equity = (balance if balance is not None else 0.0) + value'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "capital_base_usd" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1)")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
