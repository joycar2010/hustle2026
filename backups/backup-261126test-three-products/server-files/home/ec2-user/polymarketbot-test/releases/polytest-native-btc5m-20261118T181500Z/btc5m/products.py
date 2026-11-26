"""Multi-series product profiles (P7).

BTC 5m defaults are preserved: selecting another series only overlays
parameters / ledger names. Disabled phase-3/4 products refuse to run.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from btc5m.config import Config


@dataclass(frozen=True)
class ProductProfile:
    key: str
    series_slug: str
    family: str  # crypto_updown | sports_main | sports_tree | esports_props | soccer_live
    phase: int
    enabled: bool
    window_sec: int
    market_slug_prefix: str
    split_db_name: str
    maker_db_name: str
    preferred_mode: str
    description: str
    # Optional Config field overlays (never applied to btc5m baseline when key matches default)
    overlays: dict[str, Any]


# --- Phase 1: crypto up/down -------------------------------------------------
BTC_5M = ProductProfile(
    key="btc5m",
    series_slug="btc-up-or-down-5m",
    family="crypto_updown",
    phase=1,
    enabled=True,
    window_sec=300,
    market_slug_prefix="btc-updown-5m",
    split_db_name="split_sell_paper.db",
    maker_db_name="maker_paper.db",
    preferred_mode="split_sell",
    description="BTC Up/Down 5m — production baseline (do not alter defaults)",
    overlays={},
)

BTC_15M = ProductProfile(
    key="btc15m",
    series_slug="btc-up-or-down-15m",
    family="crypto_updown",
    phase=1,
    enabled=True,
    window_sec=900,
    market_slug_prefix="btc-updown-15m",
    split_db_name="split_sell_15m_paper.db",
    maker_db_name="maker_15m_paper.db",
    preferred_mode="split_sell",
    description="BTC Up/Down 15m — reuse C closed loop with longer SLAs",
    overlays={
        # Longer window → more patient fill / residual windows
        "split_touch_fill_sec": 6.0,
        "split_catchup_touch_fill_sec": 4.0,
        "split_lean_abort_sec": 35.0,
        "split_residual_sla_sec": 35.0,
        "split_stop_before_end_sec": 90.0,
        "split_merge_before_end_sec": 30.0,
        "mode": "split_sell",
    },
)

# --- Phase 2: odds bus + event state (mainline only) -------------------------
ATP = ProductProfile(
    key="atp",
    series_slug="atp",
    family="sports_main",
    phase=2,
    enabled=True,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="ATP match winner mainline — cross-book fair MM (paper)",
    overlays={"mode": "sports_mm"},
)

CS = ProductProfile(
    key="cs",
    series_slug="counter-strike",
    family="sports_main",
    phase=2,
    enabled=True,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="CS match winner mainline — cross-book fair MM (paper)",
    overlays={"mode": "sports_mm"},
)

# --- Phase 3: sports tree (scaffold only) ------------------------------------
NBA = ProductProfile(
    key="nba",
    series_slug="nba-2026",
    family="sports_tree",
    phase=3,
    enabled=False,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="NBA 2026 moneyline+spread tree — scaffold (not enabled)",
    overlays={},
)

NFL = ProductProfile(
    key="nfl",
    series_slug="nfl-2026",
    family="sports_tree",
    phase=3,
    enabled=False,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="NFL 2026 moneyline+spread tree — scaffold (not enabled)",
    overlays={},
)

# --- Phase 4: toxic / live (scaffold only) -----------------------------------
DOTA = ProductProfile(
    key="dota",
    series_slug="dota-2",
    family="esports_props",
    phase=4,
    enabled=False,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="Dota props / live — deferred (toxic books)",
    overlays={},
)

SOCCER_UNL = ProductProfile(
    key="soccer_unl",
    series_slug="soccer-unl",
    family="soccer_live",
    phase=4,
    enabled=False,
    window_sec=0,
    market_slug_prefix="",
    split_db_name="unused.db",
    maker_db_name="unused.db",
    preferred_mode="sports_mm",
    description="UEFA Nations League live — deferred (goal jumps)",
    overlays={},
)

PRODUCTS: dict[str, ProductProfile] = {
    BTC_5M.series_slug: BTC_5M,
    BTC_5M.key: BTC_5M,
    BTC_15M.series_slug: BTC_15M,
    BTC_15M.key: BTC_15M,
    ATP.series_slug: ATP,
    ATP.key: ATP,
    CS.series_slug: CS,
    CS.key: CS,
    NBA.series_slug: NBA,
    NBA.key: NBA,
    NFL.series_slug: NFL,
    NFL.key: NFL,
    DOTA.series_slug: DOTA,
    DOTA.key: DOTA,
    SOCCER_UNL.series_slug: SOCCER_UNL,
    SOCCER_UNL.key: SOCCER_UNL,
}


def get_product(name: str) -> ProductProfile:
    key = (name or "").strip().lower()
    if key not in PRODUCTS:
        known = sorted({p.series_slug for p in PRODUCTS.values()})
        raise KeyError(f"unknown product {name!r}; known={known}")
    return PRODUCTS[key]


def apply_product(cfg: Config, name: Optional[str] = None) -> tuple[Config, ProductProfile]:
    """Overlay product profile onto Config. BTC 5m → identity (no behavioral change)."""
    slug = (name or cfg.series_slug or BTC_5M.series_slug).strip()
    product = get_product(slug)
    if not product.enabled:
        raise RuntimeError(
            f"product {product.series_slug} is phase-{product.phase} scaffold only "
            f"({product.description})"
        )
    updates: dict[str, Any] = {
        "series_slug": product.series_slug,
        "window_sec": product.window_sec if product.window_sec > 0 else cfg.window_sec,
        "market_slug_prefix": product.market_slug_prefix or cfg.market_slug_prefix,
        "split_db_name": product.split_db_name,
        "maker_db_name": product.maker_db_name,
        "product_key": product.key,
    }
    updates.update(product.overlays)
    return replace(cfg, **updates), product


def list_products() -> list[ProductProfile]:
    seen: set[str] = set()
    out: list[ProductProfile] = []
    for p in (BTC_5M, BTC_15M, ATP, CS, NBA, NFL, DOTA, SOCCER_UNL):
        if p.key in seen:
            continue
        seen.add(p.key)
        out.append(p)
    return out