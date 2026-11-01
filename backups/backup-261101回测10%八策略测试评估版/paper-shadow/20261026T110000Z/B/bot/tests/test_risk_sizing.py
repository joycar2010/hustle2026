from __future__ import annotations

from bot.config import Config
from bot.risk import market_buy_amount_and_shares, target_order_size


def make_cfg() -> Config:
    return Config(
        private_key="0x" + "1" * 64,
        wallet_address="0x" + "2" * 40,
        funder_address="0x" + "3" * 40,
        signature_type=3,
        chain_id=137,
        clob_host="https://clob.polymarket.com",
        gamma_host="https://gamma-api.polymarket.com",
        polygon_rpc="https://polygon-bor-rpc.publicnode.com",
        api_key="key",
        api_secret="secret",
        api_passphrase="passphrase",
    )


def test_full_risk_fraction_can_use_full_market_buy_amount_at_99c():
    cfg = make_cfg()
    size = target_order_size(
        cfg,
        ask_price=0.99,
        ask_size=100.0,
        equity_usd=10.0,
        fee_per_share=0.0,
        risk_fraction=1.0,
    )
    amount, shares = market_buy_amount_and_shares(
        0.99,
        size,
        tick_size=0.01,
        min_notional_usd=cfg.effective_min_order_notional_usd,
    )

    assert amount == 10.0
    assert shares == 10.101


def test_partial_risk_fraction_keeps_conservative_rounding():
    cfg = make_cfg()
    size = target_order_size(
        cfg,
        ask_price=0.99,
        ask_size=100.0,
        equity_usd=10.0,
        fee_per_share=0.0,
        risk_fraction=0.99,
    )
    amount, _ = market_buy_amount_and_shares(
        0.99,
        size,
        tick_size=0.01,
        min_notional_usd=cfg.effective_min_order_notional_usd,
    )

    assert amount == 9.9
