from decimal import Decimal

from engine.config_loader import (
    GlobalRulesSnapshot,
    FundRulesSnapshot,
    DEFAULT_GLOBAL,
    DEFAULT_FUND,
    ConfigLoader,
)


class TestGlobalRulesSnapshot:
    def test_default_values(self):
        s = GlobalRulesSnapshot()
        assert s.open_spread == Decimal("0.8")
        assert s.close_spread == Decimal("0.2")
        assert s.order_amount == Decimal("500")
        assert s.borrow_delay_sec == 3
        assert s.interest_filter == Decimal("1.0")

    def test_custom_values(self):
        s = GlobalRulesSnapshot(open_spread=Decimal("1.5"), order_amount=Decimal("1000"))
        assert s.open_spread == Decimal("1.5")
        assert s.order_amount == Decimal("1000")
        assert s.close_spread == Decimal("0.2")

    def test_frozen(self):
        s = GlobalRulesSnapshot()
        try:
            s.open_spread = Decimal("2.0")
            assert False, "Should not allow mutation"
        except AttributeError:
            pass


class TestFundRulesSnapshot:
    def test_default_values(self):
        s = FundRulesSnapshot()
        assert s.bnb_min_quantity == Decimal("0.15")
        assert s.risk_value_threshold == Decimal("1.5")
        assert s.transfer_order == "futures,spot,margin"


class TestConfigLoaderDefaults:
    def test_initial_state(self):
        loader = ConfigLoader()
        assert loader.global_rules == DEFAULT_GLOBAL
        assert loader.fund_rules == DEFAULT_FUND
        assert loader.blacklist == set()
