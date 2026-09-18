"""Structured message types exchanged between slow-loop agents.

Plain dataclasses with a to_dict() so every artifact lands as JSONL that both
humans and downstream agents can parse.  Keep fields explicit -- free text is
allowed only in `narrative`, never as a decision carrier.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def _now() -> float:
    return round(time.time(), 3)


@dataclass
class WindowReview:
    """P1 review agent: one resolved 5-minute window, attributed."""
    condition_id: str
    market_slug: str
    asset: str
    end_ts: float
    outcome_side: str                  # which side won (UP/DOWN)
    n_buys: int
    n_skips: int
    top_skip_reasons: list[tuple[str, int]]
    orders: list[dict[str, Any]]       # side/price/size/result per fill
    pnl_usd: float
    pocket_hits: list[str]             # qualified pockets this window touched
    kelly_shadow_rows: int             # shadow lines seen for this window
    narrative: str = ""                # optional LLM color, advisory only
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PocketDrift:
    """P2 search agent: one pocket whose recent results diverge from table."""
    pocket: str                        # "BTC/120-180s/0.86"
    table_p_hat: float
    recent_win_rate: float
    recent_n: int
    z_score: float                     # negative = underperforming
    verdict: str                       # "ok" | "degraded" | "insufficient"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Proposal:
    """A bounded parameter-change suggestion. NEVER self-applying: it is
    written to proposals.jsonl and waits for a human (P1 governance)."""
    key: str                           # whitelisted parameter name
    current: Any
    proposed: Any
    reason: str
    source_agent: str
    confidence: str = "low"            # low|medium|high, set by desk
    status: str = "PENDING_HUMAN"      # gate.py never sets anything else
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WhaleProfile:
    """P2 whale agent: entry-behavior profile of a tracked profitable trader
    (static research dataset -- labeled as such, no fabricated win rates)."""
    trader: str
    n_trades: int
    assets: list[str]
    top_cells: list[dict]              # {asset, t_bucket, price_band, share, n}
    avg_notional_usd: float
    source: str                        # dataset provenance, honest labeling

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RegimeReport:
    """P2 shill agent v1: market-internal sentiment proxy (no external news
    source wired yet -- says so explicitly instead of pretending)."""
    asset: str
    windows: int
    up_share: float
    flip_rate: float                   # P(outcome flips vs previous window)
    regime: str                        # trending | choppy | neutral
    source: str = "outcome-series proxy (no external sentiment feed)"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeskDigest:
    """P2 desk agent: the daily/hourly aggregation of everything above."""
    period: str
    reviews: int
    total_pnl_usd: float
    win_rate: Optional[float]
    drifts: list[dict]
    proposals: list[dict]
    consensus: Optional[dict] = None   # optional dual-model check result
    extras: Optional[dict] = None      # whale profile / regime report etc.
    narrative: str = ""
    ts: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


def write_jsonl(path, obj) -> None:
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj.to_dict() if hasattr(obj, "to_dict") else obj,
                           ensure_ascii=False) + "\n")
