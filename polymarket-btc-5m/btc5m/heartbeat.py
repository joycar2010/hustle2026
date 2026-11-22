"""Process heartbeat for A/B paper engines (P2 watchdog)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class Heartbeat:
    mode: str
    ts: float
    market_slug: str = ""
    detail: str = ""
    pnl_usd: float = 0.0
    open_positions: int = 0

    @property
    def age_sec(self) -> float:
        return max(time.time() - self.ts, 0.0)


def heartbeat_path(data_dir: Path, mode: str) -> Path:
    return data_dir / f"heartbeat_{mode}.json"


def write_heartbeat(
    data_dir: Path,
    *,
    mode: str,
    market_slug: str = "",
    detail: str = "",
    pnl_usd: float = 0.0,
    open_positions: int = 0,
) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = heartbeat_path(data_dir, mode)
    payload = Heartbeat(
        mode=mode,
        ts=time.time(),
        market_slug=market_slug,
        detail=detail,
        pnl_usd=pnl_usd,
        open_positions=open_positions,
    )
    path.write_text(json.dumps(asdict(payload), ensure_ascii=False))
    return path


def read_heartbeat(data_dir: Path, mode: str) -> Optional[Heartbeat]:
    path = heartbeat_path(data_dir, mode)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return Heartbeat(**raw)
    except Exception:  # noqa: BLE001
        return None


def status_report(
    data_dir: Path,
    *,
    modes: tuple[str, ...] = (
        "late_edge",
        "late_edge_eth5m",
        "late_edge_sol5m",
        "late_edge_xrp5m",
        "late_edge_bnb5m",
        "late_edge_doge5m",
        "late_edge_hype5m",
        "maker",
        "split_sell",
        "split_sell_15m",
        "sports_mm",
        "sports_mm_atp",
        "sports_mm_cs",
        "sports_mm_nba",
        "sports_mm_nfl",
        "sports_mm_dota",
        "sports_mm_soccer_unl",
    ),
    stale_sec: float = 120.0,
) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    alerts: list[str] = []
    for mode in modes:
        hb = read_heartbeat(data_dir, mode)
        if hb is None:
            groups[mode] = {"ok": False, "reason": "missing heartbeat"}
            alerts.append(f"{mode}: missing heartbeat")
            continue
        stale = hb.age_sec > stale_sec
        groups[mode] = {
            "ok": not stale,
            "age_sec": round(hb.age_sec, 1),
            "ts": hb.ts,
            "market_slug": hb.market_slug,
            "detail": hb.detail,
            "pnl_usd": hb.pnl_usd,
            "open_positions": hb.open_positions,
            "stale": stale,
        }
        if stale:
            alerts.append(f"{mode}: stale {hb.age_sec:.0f}s > {stale_sec:.0f}s")
    return {
        "ok": not alerts,
        "alerts": alerts,
        "groups": groups,
        "stale_sec": stale_sec,
        "checked_at": time.time(),
    }
