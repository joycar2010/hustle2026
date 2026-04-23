"""Regression: broadcast_tasks.py net-asset threshold checker MUST locate the Binance
(platform_id=1) and the hedge-side (Bybit or IC Markets — platform_id in {2,3}) account
from `aggregated_data["accounts"]` where `platform_id` is stored as a raw int from
`accounts.platform_id` (SmallInteger).

The actual bug (2026-04-23): the filter was `acc.get("platform_id") == "binance"` —
comparing int to str, always False. This test would have caught it the day it was written.

We don't import broadcast_tasks.py (it wires a lot of startup-time stuff). Instead we
replicate the exact filter expression to lock the contract.
"""
import pytest

from app.core.platform import PlatformId, HEDGE_SIDE_IDS


def _aggregated_fixture():
    # Shape sourced from `account_service.get_aggregated_account_data()` (see
    # account_service.py:1470 — "platform_id": platform_id where platform_id is int).
    return {
        "summary": {"net_assets": 118733.27},
        "accounts": [
            {"platform_id": 1, "balance": {"net_assets": 92302.78}},    # Binance
            {"platform_id": 2, "balance": {"net_assets": 27582.45}},    # Bybit (MT5 bridged)
        ],
    }


def _find_binance(aggregated):
    """Must match the live expression in broadcast_tasks.py — if you refactor one, refactor the other."""
    return next(
        (acc for acc in aggregated.get("accounts", [])
         if PlatformId.from_key(acc.get("platform_id")) == PlatformId.BINANCE),
        None,
    )


def _find_hedge(aggregated):
    return next(
        (acc for acc in aggregated.get("accounts", [])
         if (PlatformId.from_key(acc.get("platform_id")) or 0) in HEDGE_SIDE_IDS),
        None,
    )


def test_finds_binance_account_with_int_platform_id():
    agg = _aggregated_fixture()
    hit = _find_binance(agg)
    assert hit is not None, "Binance account MUST be located — regression of the 2026-04-23 bug"
    assert hit["platform_id"] == 1
    assert hit["balance"]["net_assets"] == 92302.78


def test_finds_hedge_account_with_int_platform_id():
    agg = _aggregated_fixture()
    hit = _find_hedge(agg)
    assert hit is not None
    assert hit["platform_id"] == 2  # Bybit side


def test_find_hedge_also_matches_ic_markets():
    agg = {"accounts": [{"platform_id": 3, "balance": {"net_assets": 1.0}}]}
    assert _find_hedge(agg) is not None, "platform_id=3 (IC Markets) must be treated as hedge side"


def test_does_not_match_when_platform_absent():
    agg = {"accounts": [{"platform_id": None, "balance": {"net_assets": 1.0}}]}
    assert _find_binance(agg) is None
    assert _find_hedge(agg) is None


def test_filter_rejects_legacy_string_bug_shape():
    # The old bug: platform_id came in as a string like "binance" — in current code paths
    # it comes from DB smallint, but if future code accidentally converts it to a string,
    # our filter must still work (PlatformId.from_key handles both shapes).
    agg = {"accounts": [{"platform_id": "binance", "balance": {"net_assets": 1.0}}]}
    assert _find_binance(agg) is not None, "from_key must canonicalize string-shape platform_id too"


def test_raw_string_equality_is_still_a_bug_trap():
    # The scenario that used to silently fail: raw `acc["platform_id"] == "binance"` with
    # an int platform_id. Assert this ON ITS OWN to document the trap.
    agg = _aggregated_fixture()
    assert next((a for a in agg["accounts"] if a["platform_id"] == "binance"), None) is None
    # …whereas the canonical filter DOES find it:
    assert _find_binance(agg) is not None
