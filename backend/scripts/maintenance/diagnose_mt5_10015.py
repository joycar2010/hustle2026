"""
MT5 retcode=10015 Error Deep Diagnosis Script
Diagnose root cause of Bybit MT5 order failures in reverse arbitrage strategy
"""

import sys
sys.path.append('/c/app/hustle2026/backend')

# Simulate reverse arbitrage opening price calculation
def test_reverse_arbitrage_pricing():
    """Test reverse arbitrage opening price calculation logic"""

    # Simulate current market data (real data from logs)
    binance_bid = 5172.75
    binance_ask = 5172.76
    bybit_bid = 5172.03
    bybit_ask = 5172.23

    print("=" * 80)
    print("Reverse Arbitrage Opening Price Calculation Test")
    print("=" * 80)

    print(f"\nCurrent Market Data:")
    print(f"  Binance: bid={binance_bid}, ask={binance_ask}")
    print(f"  Bybit:   bid={bybit_bid}, ask={bybit_ask}")

    # Reverse arbitrage opening logic: Sell Binance, Buy Bybit
    # From arbitrage_strategy.py lines 131-133
    binance_sell_price = round(binance_ask - 0.01, 2)
    bybit_buy_price = round(bybit_ask - 0.01, 2)

    print(f"\nCalculated Order Prices:")
    print(f"  Binance SELL price: {binance_sell_price} (ask - 0.01 = {binance_ask} - 0.01)")
    print(f"  Bybit BUY price:    {bybit_buy_price} (ask - 0.01 = {bybit_ask} - 0.01)")

    # MT5 limit order rule check
    print(f"\nMT5 Limit Order Rule Check:")
    print(f"  BUY LIMIT rule: price must be < current ask")
    print(f"  Bybit BUY price {bybit_buy_price} < Bybit ask {bybit_ask}? {bybit_buy_price < bybit_ask}")

    if bybit_buy_price >= bybit_ask:
        print(f"  ERROR: Bybit buy price {bybit_buy_price} >= ask {bybit_ask}")
        print(f"  This will cause MT5 retcode=10015 (Invalid price)")
    else:
        print(f"  OK: Bybit buy price {bybit_buy_price} < ask {bybit_ask}")

    # Check price precision
    print(f"\nPrice Precision Check:")
    print(f"  Binance SELL price decimals: {len(str(binance_sell_price).split('.')[-1])}")
    print(f"  Bybit BUY price decimals:    {len(str(bybit_buy_price).split('.')[-1])}")

    # Float precision test
    print(f"\nFloat Precision Test:")
    test_price = bybit_ask - 0.01
    rounded_price = round(test_price, 2)
    print(f"  Raw calculation: {bybit_ask} - 0.01 = {test_price}")
    print(f"  After round():   {rounded_price}")
    print(f"  Precision diff:  {abs(test_price - rounded_price)}")

    # Test edge cases
    print(f"\nEdge Case Tests:")
    test_cases = [
        (5172.23, 5172.22),  # Normal case
        (5172.01, 5172.00),  # Boundary case
        (5172.00, 5171.99),  # Cross integer boundary
    ]

    for ask, expected in test_cases:
        calculated = round(ask - 0.01, 2)
        status = "OK" if calculated == expected else "ERROR"
        print(f"  {status} ask={ask}, ask-0.01={calculated}, expected={expected}")

def test_mt5_price_validation():
    """Test MT5 price validation logic"""

    print("\n" + "=" * 80)
    print("MT5 Price Validation Logic Test")
    print("=" * 80)

    # Test different price scenarios
    scenarios = [
        {
            "name": "Normal price",
            "ask": 5172.23,
            "bid": 5172.03,
            "buy_price": 5172.22,
            "expected_valid": True
        },
        {
            "name": "Buy price equals ask",
            "ask": 5172.23,
            "bid": 5172.03,
            "buy_price": 5172.23,
            "expected_valid": False
        },
        {
            "name": "Buy price higher than ask",
            "ask": 5172.23,
            "bid": 5172.03,
            "buy_price": 5172.24,
            "expected_valid": False
        },
    ]

    for scenario in scenarios:
        print(f"\nScenario: {scenario['name']}")
        print(f"  ask={scenario['ask']}, bid={scenario['bid']}")
        print(f"  buy_price={scenario['buy_price']}")

        is_valid = scenario['buy_price'] < scenario['ask']
        status = "OK" if is_valid == scenario['expected_valid'] else "ERROR"

        print(f"  {status} Price valid: {is_valid} (expected: {scenario['expected_valid']})")

        if not is_valid:
            print(f"  WARNING: This will cause MT5 retcode=10015 error")

def test_decimal_precision():
    """Test decimal module precision handling"""
    from decimal import Decimal, ROUND_HALF_UP

    print("\n" + "=" * 80)
    print("Decimal Precision Handling Test")
    print("=" * 80)

    test_values = [
        5172.23,
        5172.01,
        5172.00,
        5171.99,
    ]

    print(f"\nCompare round() vs Decimal:")
    for value in test_values:
        # Using round
        result_round = round(value - 0.01, 2)

        # Using Decimal
        decimal_value = Decimal(str(value))
        decimal_result = (decimal_value - Decimal('0.01')).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP
        )
        result_decimal = float(decimal_result)

        diff = abs(result_round - result_decimal)
        status = "OK" if diff < 0.0001 else "ERROR"

        print(f"  {status} {value} - 0.01:")
        print(f"      round():   {result_round}")
        print(f"      Decimal(): {result_decimal}")
        print(f"      diff:      {diff}")

if __name__ == "__main__":
    test_reverse_arbitrage_pricing()
    test_mt5_price_validation()
    test_decimal_precision()

    print("\n" + "=" * 80)
    print("Diagnosis Summary")
    print("=" * 80)
    print("""
Key Findings:
1. Reverse arbitrage opening uses ask - 0.01 to calculate buy price
2. MT5 BUY LIMIT requires: price < current ask
3. If spread is very small (< 0.01), calculated price may be >= ask
4. This causes MT5 to reject order with retcode=10015

Recommended Fix:
1. Use ask - 0.02 or larger offset
2. Add price validity check: ensure buy_price < ask
3. If price invalid, use ask - 0.02 as fallback
    """)
