"""P10: XRP/BNB/DOGE/HYPE 5m paper late_edge scaffolds (SOL-like, bp-scaled)."""
from __future__ import annotations

from pathlib import Path

import pytest

from btc5m.dashboard_api import (
    _LATE_EDGE_PRODUCTS,
    _filter_slug_prefix,
    _product_db_path,
    _resolve_group_db,
)
from btc5m.products import (
    BNB_5M,
    DOGE_5M,
    HYPE_5M,
    SOL_5M,
    XRP_5M,
    apply_product,
    list_products,
)
from btc5m.signal import _ASSET_OPEN, _ASSET_SPOT
from conftest import make_cfg


@pytest.mark.parametrize(
    "key,profile,asset,prefix,db",
    [
        ("xrp5m", XRP_5M, "xrp", "xrp-updown-5m", "paper_xrp5m.db"),
        ("bnb5m", BNB_5M, "bnb", "bnb-updown-5m", "paper_bnb5m.db"),
        ("doge5m", DOGE_5M, "doge", "doge-updown-5m", "paper_doge5m.db"),
        ("hype5m", HYPE_5M, "hype", "hype-updown-5m", "paper_hype5m.db"),
    ],
)
def test_alt_crypto_overlays(key, profile, asset, prefix, db):
    cfg, product = apply_product(make_cfg(), key)
    assert product is profile
    assert product.enabled
    assert cfg.mode == "late_edge"
    assert cfg.crypto_asset == asset
    assert cfg.series_slug == f"{asset}-up-or-down-5m"
    assert cfg.market_slug_prefix == prefix
    assert cfg.late_edge_db_name == db
    assert cfg.lead_table_enabled is False
    assert cfg.max_entry_price <= 0.78
    # Asymmetric SOL-like Δ (UP smaller absolute than DOWN)
    assert cfg.up_min_delta_usd > 0
    assert cfg.down_max_delta_usd < 0
    assert abs(cfg.down_max_delta_usd) > cfg.up_min_delta_usd


def test_bp_scaling_matches_sol_template():
    """XRP/HYPE Δ ≈ SOL bp × spot_ref (not SOL absolute dollars)."""
    sol = apply_product(make_cfg(), "sol5m")[0]
    xrp = apply_product(make_cfg(), "xrp5m")[0]
    # SOL ~17bp up at ~$70 → 0.12; XRP ref 0.93 → ~0.0016
    assert xrp.up_min_delta_usd == pytest.approx(0.93 * 0.00171, rel=0.02)
    assert abs(xrp.down_max_delta_usd) == pytest.approx(0.93 * 0.00285, rel=0.02)
    # Must not copy SOL absolute 0.12 onto XRP
    assert xrp.up_min_delta_usd < sol.up_min_delta_usd * 0.1


def test_signal_venues_cover_new_assets():
    for asset in ("xrp", "doge", "bnb", "hype"):
        assert asset in _ASSET_SPOT
        assert asset in _ASSET_OPEN
        assert "okx" in _ASSET_SPOT[asset]
    assert "binance" in _ASSET_SPOT["bnb"]
    assert "binance" in _ASSET_SPOT["hype"]
    assert "coinbase" in _ASSET_SPOT["xrp"]


def test_list_products_includes_alts_after_sol():
    keys = [p.key for p in list_products()]
    assert keys[:4] == ["btc5m", "btc15m", "eth5m", "sol5m"]
    for k in ("xrp5m", "bnb5m", "doge5m", "hype5m"):
        assert k in keys
    # sports still after crypto alts
    assert keys.index("xrp5m") < keys.index("atp")


def test_dashboard_routing_alt_ledgers(tmp_path: Path, monkeypatch):
    from btc5m import dashboard_api as dash

    cfg = make_cfg(data_dir=tmp_path)
    monkeypatch.setattr(dash, "load", lambda: cfg)
    for key, slug in (
        ("xrp5m", "xrp-updown-5m-1"),
        ("bnb5m", "bnb-updown-5m-1"),
        ("doge5m", "doge-updown-5m-1"),
        ("hype5m", "hype-updown-5m-1"),
    ):
        assert key in _LATE_EDGE_PRODUCTS
        g, path = _resolve_group_db(key)
        assert g == key
        assert path.name == f"paper_{key}.db"
        assert _product_db_path(key).name == f"paper_{key}.db"
        items = [
            {"market_slug": "btc-updown-5m-9", "id": 1},
            {"market_slug": slug, "id": 2},
        ]
        filtered = _filter_slug_prefix(items, key)
        assert [i["id"] for i in filtered] == [2]


def test_engine_alt_ledger_and_heartbeat(tmp_path: Path):
    from btc5m.engine import Engine

    cfg, _ = apply_product(make_cfg(data_dir=tmp_path), "xrp5m")
    eng = Engine(cfg, live=False)
    assert eng.store.path.name == "paper_xrp5m.db"
    assert eng._hb_mode == "late_edge_xrp5m"


def test_btc5m_identity_untouched():
    cfg = make_cfg()
    out, product = apply_product(cfg, "btc5m")
    assert product.key == "btc5m"
    assert out.crypto_asset == "btc"
    assert out.late_edge_db_name == "paper.db"
    assert out.up_min_delta_usd == cfg.up_min_delta_usd


def test_thin_books_tighter_than_sol():
    sol = SOL_5M.overlays
    doge = DOGE_5M.overlays
    hype = HYPE_5M.overlays
    assert doge["max_entry_price"] < sol["max_entry_price"]
    assert hype["max_entry_price"] < sol["max_entry_price"]
    assert doge["opening_gap_min_bp"] > sol["opening_gap_min_bp"]
    assert BNB_5M.overlays["max_entry_price"] < sol["max_entry_price"]
