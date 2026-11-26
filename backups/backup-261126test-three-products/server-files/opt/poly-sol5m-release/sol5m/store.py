"""SOL ledger wrapper with an explicit isolated database path."""
from __future__ import annotations

from pathlib import Path

from btc5m.store import Store as _Store
from sol5m.profile import SOL5M


class Sol5mStore(_Store):
    """Store that defaults to ``data/paper_sol5m.db`` in this release."""

    def __init__(self, path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        super().__init__(path or root / "data" / SOL5M.late_edge_db_name)


__all__ = ["Sol5mStore"]

