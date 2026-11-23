"""P11: BTC5m solgate half shadow + BTC15m late_edge paper."""
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
    BTC_15M,
    BTC_15M_LE,
    BTC_5M,
    BTC_5M_SOLGATE,
    apply_product,
    list_products,
)
from conftest import make_cfg


def test_btc5m_solgate_half_overlays():
    cfg, product = apply_product(make_cfg(), "btc5m_solgate")
    assert product is BTC_5M_SOLGATE
    assert cfg.mode == "late_edge"
    assert cfg.crypto_asset == "btc"
    assert cfg.series_slug == "btc-up-or-down-5m"
    assert cfg.market_slug_prefix == "btc-updown-5m"
    assert cfg.late_edge_db_name == "paper_btc5m_solgate.db"
    assert cfg.lead_table_enabled is True
    assert cfg.max_entry_price == 0.78
    assert cfg.opening_gap_max_entry_price == 0.76
    assert cfg.lead_min_bp == 2.5
    assert cfg.up_lead_min_bp == 2.0
    assert cfg.down_lead_min_bp == 3.5
    assert cfg.opening_gap_min_bp == 6.5
    # 10bp / 16bp @ 90k
    assert cfg.up_min_delta_usd == pytest.approx(90.0)
    assert cfg.down_max_delta_usd == pytest.approx(-144.0)
    # Stricter than frozen A dollar gates ($20 / -$30) in absolute Δ
    baseline = apply_product(make_cfg(), "btc5m")[0]
    assert cfg.up_min_delta_usd > baseline.up_min_delta_usd
    assert abs(cfg.down_max_delta_usd) > abs(baseline.down_max_delta_usd)


def test_btc15m_le_time_stretch():
    cfg, product = apply_product(make_cfg(), "btc15m_le")
    assert product is BTC_15M_LE
    assert cfg.mode == "late_edge"
    assert cfg.window_sec == 900
    assert cfg.series_slug == "btc-up-or-down-15m"
    assert cfg.late_edge_db_name == "paper_btc15m.db"
    assert cfg.entry_window_sec == 120.0
    assert cfg.min_t_remaining_sec == 30.0
    assert cfg.opening_gap_window_sec == 120.0
    assert cfg.confirm_checks == 4
    assert cfg.lead_table_enabled is True
    assert cfg.up_min_delta_usd == pytest.approx(90.0)


def test_btc15m_c_untouched():
    cfg, product = apply_product(make_cfg(), "btc15m")
    assert product is BTC_15M
    assert cfg.mode == "split_sell"
    assert cfg.split_db_name == "split_sell_15m_paper.db"
    assert cfg.split_stop_before_end_sec == 90.0


def test_btc5m_baseline_identity():
    cfg = make_cfg()
    out, product = apply_product(cfg, "btc5m")
    assert product is BTC_5M
    assert out.late_edge_db_name == "paper.db"
    assert out.up_min_delta_usd == cfg.up_min_delta_usd
    assert out.lead_table_enabled == cfg.lead_table_enabled
    assert BTC_5M.overlays == {}


def test_list_products_includes_p11_keys():
    keys = [p.key for p in list_products()]
    assert keys[0] == "btc5m"
    assert "btc5m_solgate" in keys
    assert "btc15m_le" in keys
    assert keys.index("btc5m_solgate") < keys.index("btc15m")
    assert keys.index("btc15m") < keys.index("btc15m_le")
    assert keys.index("btc15m_le") < keys.index("eth5m")


def test_dashboard_routing_p11(tmp_path: Path, monkeypatch):
    from btc5m import dashboard_api as dash

    cfg = make_cfg(data_dir=tmp_path)
    monkeypatch.setattr(dash, "load", lambda: cfg)

    assert "btc5m_solgate" in _LATE_EDGE_PRODUCTS
    assert "btc15m_le" in _LATE_EDGE_PRODUCTS

    g, path = _resolve_group_db("btc5m_solgate")
    assert g == "btc5m_solgate"
    assert path.name == "paper_btc5m_solgate.db"
    assert _product_db_path("btc5m_solgate").name == "paper_btc5m_solgate.db"

    g2, path2 = _resolve_group_db("btc15m_le")
    assert g2 == "btc15m_le"
    assert path2.name == "paper_btc15m.db"
    assert _product_db_path("btc15m_le").name == "paper_btc15m.db"
    # C product still points at split ledger
    assert _product_db_path("btc15m").name == "split_sell_15m_paper.db"

    items = [
        {"market_slug": "btc-updown-5m-1", "id": 1},
        {"market_slug": "btc-updown-15m-1", "id": 2},
        {"market_slug": "sol-updown-5m-1", "id": 3},
    ]
    assert [i["id"] for i in _filter_slug_prefix(items, "btc5m_solgate")] == [1]
    assert [i["id"] for i in _filter_slug_prefix(items, "btc15m_le")] == [2]


def test_engine_ledgers_and_heartbeats(tmp_path: Path):
    from btc5m.engine import Engine

    cfg5, _ = apply_product(make_cfg(data_dir=tmp_path), "btc5m_solgate")
    eng5 = Engine(cfg5, live=False)
    assert eng5.store.path.name == "paper_btc5m_solgate.db"
    assert eng5._hb_mode == "late_edge_btc5m_solgate"

    cfg15, _ = apply_product(make_cfg(data_dir=tmp_path), "btc15m_le")
    eng15 = Engine(cfg15, live=False)
    assert eng15.store.path.name == "paper_btc15m.db"
    assert eng15._hb_mode == "late_edge_btc15m_le"


def test_cli_btc15m_late_edge_remaps(tmp_path: Path, monkeypatch):
    """--series btc15m --mode late_edge should land on btc15m_le ledger."""
    from btc5m import __main__ as main_mod
    from btc5m.products import apply_product as ap

    def _load(*, series=None):
        cfg = make_cfg(data_dir=tmp_path)
        return ap(cfg, series or "btc15m")[0]

    monkeypatch.setattr(main_mod, "load", _load)

    captured: dict = {}

    class FakeEngine:
        def __init__(self, cfg, live=False):
            captured["cfg"] = cfg
            captured["live"] = live

        def run(self, once=False):
            captured["once"] = once

    monkeypatch.setattr("btc5m.engine.Engine", FakeEngine)
    rc = main_mod.main(
        ["--series", "btc15m", "--mode", "late_edge", "--once"]
    )
    assert rc == 0
    assert captured["cfg"].product_key == "btc15m_le"
    assert captured["cfg"].late_edge_db_name == "paper_btc15m.db"
    assert captured["cfg"].mode == "late_edge"
    assert captured["once"] is True
