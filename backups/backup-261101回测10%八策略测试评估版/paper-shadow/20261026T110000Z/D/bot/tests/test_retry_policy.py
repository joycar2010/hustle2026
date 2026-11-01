from bot.main import (
    _update_buy_retry_state,
    buy_limit_price,
    retry_chase_block_reason,
)


def test_negative_retry_drift_disables_chase_guard():
    assert (
        retry_chase_block_reason(
            retry_side="UP",
            retry_reference_price=0.94,
            order_limit_price=0.98,
            fresh_ask=0.97,
            tick_size=0.01,
            max_retry_price_drift_ticks=-1,
        )
        is None
    )


def test_zero_retry_drift_blocks_a_higher_retry_limit():
    reason = retry_chase_block_reason(
        retry_side="UP",
        retry_reference_price=0.94,
        order_limit_price=0.98,
        fresh_ask=0.97,
        tick_size=0.01,
        max_retry_price_drift_ticks=0,
    )
    assert reason == (
        "retry limit=0.98 > first_attempt=0.94 + drift=0.00; fresh_ask=0.97"
    )


def test_buy_at_price_cap_does_not_add_a_tick():
    assert (
        buy_limit_price(
            fresh_ask=0.99,
            price_buffer=0.01,
            price_cap=0.99,
        )
        == 0.99
    )


def test_buy_buffer_still_applies_below_price_cap():
    assert (
        buy_limit_price(
            fresh_ask=0.98,
            price_buffer=0.01,
            price_cap=0.99,
        )
        == 0.99
    )


def test_failed_buy_records_retry_without_marking_market_bought():
    bought_this_window: set[str] = set()
    buy_retry_sides: dict[tuple[str, str], str] = {}
    buy_retry_entry_rules: dict[tuple[str, str], str] = {}
    buy_retry_reference_prices = {
        ("condition", "initial", "DOWN"): 0.99,
    }

    filled = _update_buy_retry_state(
        condition_id="condition",
        retry_slot="initial",
        retry_key=("condition", "initial", "DOWN"),
        side="DOWN",
        entry_rule="edge",
        filled_size=0.0,
        bought_this_window=bought_this_window,
        buy_retry_sides=buy_retry_sides,
        buy_retry_entry_rules=buy_retry_entry_rules,
        buy_retry_reference_prices=buy_retry_reference_prices,
    )

    assert filled is False
    assert "condition" not in bought_this_window
    assert buy_retry_sides[("condition", "initial")] == "DOWN"
    assert buy_retry_reference_prices[("condition", "initial", "DOWN")] == 0.99


def test_filled_buy_marks_market_bought_and_clears_retry_state():
    bought_this_window: set[str] = set()
    buy_retry_sides = {("condition", "initial"): "DOWN"}
    buy_retry_entry_rules: dict[tuple[str, str], str] = {}
    buy_retry_reference_prices = {
        ("condition", "initial", "DOWN"): 0.99,
    }

    filled = _update_buy_retry_state(
        condition_id="condition",
        retry_slot="initial",
        retry_key=("condition", "initial", "DOWN"),
        side="DOWN",
        entry_rule="edge",
        filled_size=35.73,
        bought_this_window=bought_this_window,
        buy_retry_sides=buy_retry_sides,
        buy_retry_entry_rules=buy_retry_entry_rules,
        buy_retry_reference_prices=buy_retry_reference_prices,
    )

    assert filled is True
    assert "condition" in bought_this_window
    assert ("condition", "initial") not in buy_retry_sides
    assert ("condition", "initial", "DOWN") not in buy_retry_reference_prices
