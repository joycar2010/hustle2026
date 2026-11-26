from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from btc5m.config import load, validate_split_parameters
from btc5m.engine import Engine
from btc5m.resolver import gamma_winner_side
from btc5m.risk import beijing_day_start_ts, beijing_day_key
from btc5m.store import Store
from btc5m.dashboard_api import _daily_from_maker


def test_invalid_first_leg_cannot_silently_start():
    cfg = replace(load(), split_clip_shares=10.0, split_max_lean_shares=3.0)
    with pytest.raises(ValueError, match="clip"):
        validate_split_parameters(cfg)
    validate_split_parameters(replace(cfg, split_clip_shares=5, split_max_lean_shares=5))


@pytest.mark.parametrize("status,prices,expected", [
    ("proposed", '["1","0"]', None),
    ("resolved", '["0.96","0.04"]', None),
    ("resolved", '["1","0"]', "UP"),
])
def test_settlement_requires_final_official_result(monkeypatch, status, prices, expected):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"markets": [{"conditionId": "cid", "closed": True,
        "umaResolutionStatus": status, "outcomes": '["Up","Down"]', "outcomePrices": prices}]}
    monkeypatch.setattr("btc5m.resolver.requests.get", lambda *a, **k: response)
    assert gamma_winner_side("https://example.invalid", SimpleNamespace(condition_id="cid", market_slug="slug")) == expected


def test_a_official_pending_never_closes_position(monkeypatch):
    engine = Engine.__new__(Engine)
    engine.cfg = load()
    engine.live = False
    engine.store = Mock()
    engine.store.open_rows.return_value = [{"market_slug": "slug"}]
    monkeypatch.setattr("btc5m.markets.fetch_market_by_slug", lambda *a: SimpleNamespace(t_remaining=lambda: -300))
    monkeypatch.setattr("btc5m.engine.gamma_winner_side", lambda *a: None)
    engine._resolve_open()
    engine.store.close_position.assert_not_called()


def test_execution_and_inventory_rollback_together(tmp_path):
    store = Store(tmp_path / "paper.db")
    sid = store.open_maker_session(market_slug="s", condition_id="c", up_token="u", down_token="d", dry_run=True)
    fill = dict(market_slug="s", condition_id="c", side="UP", token_id="u", size=5,
                price=.5, fee_usd=0, liquidity="maker", strategy="maker_mm", dry_run=True)
    store.conn.execute("CREATE TRIGGER fail_inventory BEFORE UPDATE ON maker_sessions BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(Exception, match="injected"):
        store.record_maker_execution(sid, fill=fill, inventory={"up_shares": 5}, accounting={})
    assert store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
    assert store.open_maker_sessions()[0]["up_shares"] == 0


def test_empty_merge_sessions_are_not_reported_as_trades(tmp_path):
    store = Store(tmp_path / "paper.db")
    for _ in range(2):
        store.open_maker_session(market_slug="s", condition_id="c", up_token="u", down_token="d", dry_run=True)
    store.conn.execute("UPDATE maker_sessions SET status='closed',closed_ts=100,net_pnl_usd=0,merged_shares=50")
    store.conn.commit()
    store.record_fill(market_slug="s", condition_id="c", side="UP", token_id="u", size=5,
                      price=.5, fee_usd=0, liquidity="maker", strategy="split_sell", dry_run=True, session_id=2)
    day = _daily_from_maker(store.conn, 0, 200)
    assert day["settled"] == 1 and day["empty_closed_sessions"] == 1


def test_day_boundary_is_beijing_midnight():
    before = datetime(2026, 11, 19, 15, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 19, 16, 0, 0, tzinfo=timezone.utc)
    assert beijing_day_key(before) == "2026-11-19"
    assert beijing_day_key(after) == "2026-11-20"
    assert beijing_day_start_ts(after) - beijing_day_start_ts(before) == 86400


def test_filled_pending_session_is_visible_before_official_settlement(tmp_path):
    store = Store(tmp_path / "paper.db")
    sid = store.open_maker_session(market_slug="s", condition_id="c", up_token="u", down_token="d", dry_run=True)
    store.record_fill(market_slug="s", condition_id="c", side="UP", token_id="u", size=5,
                      price=.5, fee_usd=0, liquidity="maker", strategy="split_sell", dry_run=True, session_id=sid)
    day = _daily_from_maker(store.conn, 0, 1e12)
    assert day["traded_sessions"] == 1 and day["fill_count"] == 1
    assert day["pending_traded_sessions"] == 1
    assert day["settled"] == 0 and day["pnl_usd"] == 0
