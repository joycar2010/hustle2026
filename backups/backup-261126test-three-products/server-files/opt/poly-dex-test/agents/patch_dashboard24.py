"""In-place patch #24: Kelly-sizing master switch in the risk settings form.

- `_kelly_sizing_enabled()`: read KELLY_SIZING_ENABLED from .env (5s cached),
  using the same truthiness the worker's kelly_sizing._env_flag applies, and
  expose it in the /api/state payload so the form can show the live state.
- PUT /api/settings/risk accepts `kelly_sizing_enabled` (bool): writes
  KELLY_SIZING_ENABLED=true/false to .env and restarts the paper workers
  (same restart the other trigger lines already perform).

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard24.py <dashboard.py>
"""
from __future__ import annotations

import sys

HELPER = '''_kelly_flag_cache: dict[str, Any] = {"ts": 0.0, "value": False}


def _kelly_sizing_enabled() -> bool:
    """Current KELLY_SIZING_ENABLED as persisted in .env (5s cached), matching
    the worker's kelly_sizing._env_flag truthiness so the toggle never lies."""
    now = time.monotonic()
    if now - _kelly_flag_cache["ts"] > 5.0:
        try:
            v = dotenv_values(ROOT / ".env").get("KELLY_SIZING_ENABLED") or "false"
            _kelly_flag_cache["value"] = str(v).strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            pass
        _kelly_flag_cache["ts"] = now
    return bool(_kelly_flag_cache["value"])


@app.put("/api/settings/risk")
async def put_risk_settings(request: Request):'''

BRANCH = '''    if body.get("kelly_sizing_enabled") is not None:
        kelly_on = bool(body["kelly_sizing_enabled"])
        changes["KELLY_SIZING_ENABLED"] = "true" if kelly_on else "false"
        _kelly_flag_cache["ts"] = 0.0
        note.append("凯利拉闸=" + ("开" if kelly_on else "关"))
    if not changes:
        raise HTTPException(status_code=400, detail="没有可应用的字段")'''

E = [
    # helper + state key
    ('@app.put("/api/settings/risk")\nasync def put_risk_settings(request: Request):', HELPER),
    ('        "today_counts": _today_counts(),',
     '        "today_counts": _today_counts(),\n        "kelly_sizing_enabled": _kelly_sizing_enabled(),'),
    # PUT branch
    ('    if not changes:\n        raise HTTPException(status_code=400, detail="没有可应用的字段")',
     BRANCH),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_kelly_sizing_enabled" in src:
        print("already patched")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT anchor #{i} count={src.count(old)}")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
