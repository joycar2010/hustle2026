"""Contract tests for :class:`app.core.platform.PlatformId`.

These assertions are the tripwire for the whole refactor: if someone reintroduces a
`"binance"`/`1` magic literal, at least one of the tests below goes red.
"""
import pytest

from app.core.platform import PlatformId, HEDGE_SIDE_IDS


def test_enum_values_are_stable():
    # DB stores these as smallint FKs to platforms.platform_id — the integer assignment
    # is a data contract, never change these without a migration.
    assert PlatformId.BINANCE == 1
    assert PlatformId.BYBIT == 2
    assert PlatformId.IC_MARKETS == 3
    assert PlatformId.GATE == 4


def test_canonical_key_matches_legacy_strings():
    # orders.platform / platforms.platform_name historical lowercase values
    assert PlatformId.BINANCE.key == "binance"
    assert PlatformId.BYBIT.key == "bybit"
    assert PlatformId.IC_MARKETS.key == "ic_markets"
    assert PlatformId.GATE.key == "gate"


@pytest.mark.parametrize("raw,expected", [
    ("binance", PlatformId.BINANCE),
    ("BINANCE", PlatformId.BINANCE),
    ("  Binance  ", PlatformId.BINANCE),
    ("bybit", PlatformId.BYBIT),
    ("mt5", PlatformId.BYBIT),               # legacy alias — historical data
    ("ic_markets", PlatformId.IC_MARKETS),
    ("icmarkets", PlatformId.IC_MARKETS),
    ("ic", PlatformId.IC_MARKETS),
    ("gate", PlatformId.GATE),
    ("gate_io", PlatformId.GATE),
    ("gateio", PlatformId.GATE),
    (1, PlatformId.BINANCE),
    (2, PlatformId.BYBIT),
    ("1", PlatformId.BINANCE),
    (PlatformId.BINANCE, PlatformId.BINANCE),
])
def test_from_key_accepts_all_known_shapes(raw, expected):
    assert PlatformId.from_key(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "unknown", "binacne", 99, 0, -1, "99"])
def test_from_key_rejects_unknown(bad):
    assert PlatformId.from_key(bad) is None


def test_hedge_side_ids_contract():
    # broadcast_tasks.py filters the Bybit/MT5 hedge account with this set.
    # If someone later adds a new hedge-side platform, HEDGE_SIDE_IDS must be updated.
    assert PlatformId.BYBIT.value in HEDGE_SIDE_IDS
    assert PlatformId.IC_MARKETS.value in HEDGE_SIDE_IDS
    assert PlatformId.BINANCE.value not in HEDGE_SIDE_IDS
    assert PlatformId.GATE.value not in HEDGE_SIDE_IDS


def test_intenum_compares_with_raw_smallint():
    # DB column is SmallInteger — comparisons used by account_sync_service etc. rely on
    # PlatformId behaving as an int. If someone swaps to a plain Enum this breaks silently.
    db_column_value = 1  # mocks `account.platform_id` as read from PostgreSQL smallint
    assert db_column_value == PlatformId.BINANCE
    assert PlatformId.BINANCE == 1
