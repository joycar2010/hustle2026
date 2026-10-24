"""In-place patch #5: extend the signal-error debounce to BTC and fix the
debounce epoch (start at process boot, not 0, so a restart cannot instantly
trip the 30s threshold).  Root cause being debounced: at every 5-minute
window boundary the new Chainlink open candle lags a few seconds, so both
signal loops throw "no chainlink candle found" transiently.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard5.py <path>
"""
from __future__ import annotations

import sys

E = [
    # epoch fix for the ETH debounce introduced by patch #4
    ('_eth_signal_ok = {"ts": 0.0}',
     '_eth_signal_ok = {"ts": time.time()}\n_btc_signal_ok = {"ts": time.time()}'),
    # BTC success stamp
    ('            _state["errors"].pop("btc_signal", None)',
     '            _state["errors"].pop("btc_signal", None)\n'
     '            _btc_signal_ok["ts"] = time.time()'),
    # BTC debounced error surfacing
    ('        except Exception as e:\n'
     '            _state["btc_signal"] = None\n'
     '            _state["errors"]["btc_signal"] = str(e)',
     '        except Exception as e:\n'
     '            _state["btc_signal"] = None\n'
     '            # Window-boundary candle lag is expected; surface only after\n'
     '            # 30s of continuous failure (same policy as eth_signal).\n'
     '            if time.time() - _btc_signal_ok["ts"] > 30.0:\n'
     '                _state["errors"]["btc_signal"] = str(e)'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_btc_signal_ok" in src:
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
