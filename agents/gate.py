"""Governance gate for agent proposals (P1).

Hard rules, deterministic, not bypassable by any agent:
  1. Only WHITELISTED keys may be proposed at all.
  2. Numeric values are CLAMPED into the allowed band around current.
  3. Every surviving proposal is stamped PENDING_HUMAN and appended to
     proposals.jsonl -- nothing in this codebase applies it automatically.

The whitelist deliberately covers sizing/qualification knobs only; entry-rule
logic, credentials, live switches and anything wallet-adjacent are not
proposable.
"""
from __future__ import annotations

from typing import Any, Optional

from agents.schemas import Proposal

# key -> (kind, low, high) bands; None = boolean-style value
WHITELIST: dict[str, tuple[str, float, float]] = {
    "KELLY_LAMBDA":            ("float", 0.05, 0.5),
    "KELLY_CAP_FRACTION":      ("float", 0.02, 0.15),
    "MAX_DAILY_LOSS_FRACTION": ("float", 0.02, 0.10),
    "POCKET_MIN_EDGE":         ("float", 0.002, 0.02),
    "POCKET_MIN_OBS":          ("int",   15,   100),
    "POCKET_PRIOR_STRENGTH":   ("int",   10,   200),
    "POCKET_DISABLE":          ("pocket", 0, 0),   # value = pocket key string
}


def vet(p: Proposal) -> Optional[Proposal]:
    """Return the clamped proposal, or None when the key is not proposable."""
    spec = WHITELIST.get(p.key)
    if spec is None:
        return None
    kind, lo, hi = spec
    if kind in ("float", "int"):
        try:
            v = float(p.proposed)
        except (TypeError, ValueError):
            return None
        v = max(lo, min(hi, v))
        p.proposed = int(round(v)) if kind == "int" else round(v, 4)
    elif kind == "pocket":
        if not isinstance(p.proposed, str) or p.proposed.count("/") != 2:
            return None
    p.status = "PENDING_HUMAN"
    return p


def vet_all(proposals: list[Proposal]) -> list[Proposal]:
    return [q for q in (vet(p) for p in proposals) if q is not None]
