"""In-place patch #23: fix consensus-history agreement flag.

The #22 endpoint derived `agreed` from `"一致" in reason`. That substring
test is wrong in both directions:
  - false positive: the reason "模型意见不一致" (models DISAGREE) contains
    "一致" as a substring of "不一致", so disagreements were flagged agreed.
  - false negative: a genuine double-HOLD cycle with an empty reason was
    flagged not-agreed.

Fix: derive agreement from the two model TEXTS (BUY/SELL/HOLD tokens),
which is what the modal actually shows. Arbiter `decision` is untouched.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard23.py <dashboard.py>
"""
from __future__ import annotations

import sys

OLD = '''                rows.append({
                    "ts": d.get("ts"),
                    "decision": c.get("decision"),
                    "reason": c.get("reason"),
                    "agreed": "一致" in str(c.get("reason") or ""),'''

NEW = '''                def _norm_tok(t):
                    t = str(t or "").upper()
                    for tok in ("BUY", "SELL", "HOLD"):
                        if tok in t:
                            return tok
                    return ""
                _pt = _norm_tok(c.get("primary_text"))
                _st = _norm_tok(c.get("secondary_text"))
                _ag = bool(_pt) and _pt == _st
                rows.append({
                    "ts": d.get("ts"),
                    "decision": c.get("decision"),
                    "reason": c.get("reason"),
                    "agreed": _ag,'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_norm_tok" in src:
        print("already patched")
        return 0
    if src.count(OLD) != 1:
        print(f"ABORT anchor count={src.count(OLD)}")
        return 2
    src = src.replace(OLD, NEW, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
