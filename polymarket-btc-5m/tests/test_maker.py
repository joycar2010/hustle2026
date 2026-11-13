from __future__ import annotations

from btc5m.maker import settle_maker_pnl


def test_settle_paired_profit():
    # 10 up @0.47 + 10 down @0.50 = pair 0.97 → +0.30 gross whichever wins
    r = settle_maker_pnl(
        up_shares=10,
        down_shares=10,
        up_cost=4.70,
        down_cost=5.00,
        up_fee=0.0,
        down_fee=0.0,
        winner="UP",
    )
    assert abs(r["gross_pnl_usd"] - 0.30) < 1e-9
    assert abs(r["net_pnl_usd"] - 0.30) < 1e-9
    assert r["paired_shares"] == 10
    assert abs(r["pair_cost"] - 0.97) < 1e-9
    assert r["residual_shares"] == 0


def test_settle_residual_loss():
    # Only UP filled, DOWN wins → lose full cost
    r = settle_maker_pnl(
        up_shares=10,
        down_shares=0,
        up_cost=4.80,
        down_cost=0.0,
        up_fee=0.0,
        down_fee=0.0,
        winner="DOWN",
    )
    assert abs(r["gross_pnl_usd"] - (-4.80)) < 1e-9
    assert r["residual_side"] == "UP"
    assert r["residual_shares"] == 10


def test_settle_skew_win():
    # 15 UP + 10 DOWN, UP wins: payout 15, cost 15*0.5+10*0.48
    r = settle_maker_pnl(
        up_shares=15,
        down_shares=10,
        up_cost=7.5,
        down_cost=4.8,
        up_fee=0.0,
        down_fee=0.0,
        winner="UP",
    )
    assert abs(r["gross_pnl_usd"] - (15 - 12.3)) < 1e-9
    assert r["paired_shares"] == 10
    assert r["residual_side"] == "UP"
    assert r["residual_shares"] == 5
