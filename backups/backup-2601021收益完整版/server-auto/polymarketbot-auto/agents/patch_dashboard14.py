"""In-place patch #14: paginated orders API + operator-gated risk settings.

- GET /api/orders?offset&limit&lane=all|paper|live -- full order history with
  paging, reusing recent_orders' row shaping and a lane-aware COUNT.
- PUT /api/settings/risk (X-Operator-Token) -- sets the worker trigger lines
  MAX_DAILY_LOSS_FRACTION / MAX_DAILY_REALIZED_PROFIT_USD: clamps values,
  rewrites .env (with backup), updates the dashboard's cfg for display, and
  restarts the paper workers via sudo -n so the gate change takes effect.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard14.py <path>
"""
from __future__ import annotations

import sys

BLOCK = '''@app.get("/api/orders")
def orders_page(offset: int = 0, limit: int = 20, lane: str = "all"):
    """Paginated order history (paper + live), newest first."""
    offset = max(0, min(int(offset), 5000))
    limit = max(1, min(int(limit), 100))
    lane = lane if lane in ("all", "paper", "live") else "all"
    rows = recent_orders(limit=min(5000, offset + limit * 3 + 60))
    if lane == "paper":
        rows = [r for r in rows if r.get("dry_run")]
    elif lane == "live":
        rows = [r for r in rows if not r.get("dry_run")]
    where = {"all": "", "paper": " WHERE dry_run=1", "live": " WHERE dry_run=0"}[lane]
    try:
        with db() as c:
            total = int(c.execute("SELECT COUNT(*) FROM orders" + where).fetchone()[0])
    except Exception:
        total = len(rows)
    return {"rows": rows[offset:offset + limit], "total": total,
            "offset": offset, "limit": limit, "lane": lane}


def _update_env_keys(changes: dict[str, str]) -> None:
    env_path = ROOT / ".env"
    backup = ROOT / f".env.before-risk.{time.strftime('%Y%m%d-%H%M%S')}"
    text = env_path.read_text(encoding="utf-8")
    backup.write_text(text, encoding="utf-8")
    lines = text.splitlines()
    seen = set()
    for i, line in enumerate(lines):
        for key, value in changes.items():
            if line.startswith(key + "="):
                lines[i] = f"{key}={value}"
                seen.add(key)
    for key, value in changes.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


@app.put("/api/settings/risk")
async def put_risk_settings(request: Request):
    """Operator-gated worker trigger lines; applies to .env and restarts the
    paper workers so the running gate matches what the UI shows."""
    _require_operator(request)
    body = await request.json()
    changes: dict[str, str] = {}
    note = []
    if body.get("max_daily_loss_fraction") is not None:
        loss = max(0.01, min(0.50, float(body["max_daily_loss_fraction"])))
        changes["MAX_DAILY_LOSS_FRACTION"] = f"{loss:g}"
        try:
            cfg.max_daily_loss_fraction = loss
        except Exception:
            object.__setattr__(cfg, "max_daily_loss_fraction", loss)
        note.append(f"日亏损熔断={loss:.0%}")
    if body.get("max_daily_realized_profit_usd") is not None:
        cap = max(0.0, min(10000.0, float(body["max_daily_realized_profit_usd"])))
        changes["MAX_DAILY_REALIZED_PROFIT_USD"] = f"{cap:g}"
        try:
            cfg.max_daily_realized_profit_usd = cap
        except Exception:
            object.__setattr__(cfg, "max_daily_realized_profit_usd", cap)
        note.append("每日止盈上限=" + (f"${cap:g}" if cap > 0 else "关闭"))
    if not changes:
        raise HTTPException(status_code=400, detail="没有可应用的字段")
    _update_env_keys(changes)
    restarted: list[str] = []
    if bool(body.get("restart_workers", True)):
        import subprocess
        for unit in ("polymarket-auto-btc-paper.service",
                     "polymarket-auto-eth-paper.service"):
            try:
                subprocess.run(["sudo", "-n", "systemctl", "restart", unit],
                               check=True, capture_output=True, timeout=30)
                restarted.append(unit.replace("polymarket-auto-", "").replace(".service", ""))
            except Exception:
                pass
    return {"ok": True, "applied": changes, "workers_restarted": restarted,
            "note": "；".join(note) + ("（worker 已重启生效）" if restarted else "（未重启 worker，重启后生效）")}


@app.websocket("/api/ws/state")'''


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "/api/settings/risk" in src:
        print("already patched; nothing to do")
        return 0
    anchor = '@app.websocket("/api/ws/state")'
    if src.count(anchor) != 1:
        print(f"ABORT: anchor count={src.count(anchor)} (need 1)")
        return 2
    open(path, "w", encoding="utf-8").write(src.replace(anchor, BLOCK, 1))
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
