from decimal import Decimal

from engine.trading.quantity_calc import usdt_to_quantity, round_to_step


class TestUsdtToQuantity:
    def test_normal_conversion(self):
        result = usdt_to_quantity(Decimal("500"), Decimal("100"), "0.01", "0.01")
        assert result == Decimal("5.00")

    def test_rounds_down_to_step(self):
        result = usdt_to_quantity(Decimal("500"), Decimal("99.9"), "0.01", "0.01")
        assert result == Decimal("5.00")

    def test_below_min_qty_returns_zero(self):
        result = usdt_to_quantity(Decimal("1"), Decimal("50000"), "0.001", "0.001")
        assert result == Decimal("0")

    def test_exact_step_multiple(self):
        result = usdt_to_quantity(Decimal("100"), Decimal("50"), "0.1", "0.1")
        assert result == Decimal("2.0")

    def test_large_step_size(self):
        result = usdt_to_quantity(Decimal("500"), Decimal("100"), "1", "1")
        assert result == Decimal("5")

    def test_small_quantity(self):
        result = usdt_to_quantity(Decimal("10"), Decimal("50000"), "0.00001", "0.00001")
        assert result == Decimal("0.00020")


class TestRoundToStep:
    def test_normal_rounding(self):
        result = round_to_step(Decimal("5.678"), "0.01")
        assert result == Decimal("5.67")

    def test_already_exact(self):
        result = round_to_step(Decimal("5.00"), "0.01")
        assert result == Decimal("5.00")

    def test_large_step(self):
        result = round_to_step(Decimal("5.678"), "1")
        assert result == Decimal("5")

    def test_tiny_step(self):
        result = round_to_step(Decimal("0.123456"), "0.0001")
        assert result == Decimal("0.1234")
