"""Optional Dashboard adapter for the isolated sports paper service.

Keeping this adapter separate makes it safe to add ``/api/sports/summary`` to
the existing dashboard without importing trading workers or CLOB credentials.
The service is lazy and disabled unless ``SPORTS_ENABLED=true``.
"""
from __future__ import annotations

from typing import Any

from bot.sports_main import SportsPaperService

_service: SportsPaperService | None = None


def sports_summary(cfg: Any, *, refresh: bool = True) -> dict[str, Any]:
    global _service
    if _service is None or _service.cfg is not cfg:
        _service = SportsPaperService(cfg)
    if refresh:
        try:
            _service.run_once()
        except Exception as exc:  # Dashboard must remain healthy if Gamma is down.
            snapshot = _service.snapshot(status="error")
            snapshot["error"] = str(exc)
            return snapshot
    return _service.snapshot()

