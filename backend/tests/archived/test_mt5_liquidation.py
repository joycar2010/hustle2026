"""Test MT5 liquidation price calculation"""
import MetaTrader5 as mt5
import sys

print("Testing MT5 liquidation price calculation...")

# Initialize MT5
if not mt5.initialize():
    error = mt5.last_error()
    print(f"[FAIL] MT5 initialization failed: {error}")
    sys.exit(1)

print("[OK] MT5 initialized successfully!")

# Get account info
account_info = mt5.account_info()
if account_info:
    print(f"\n=== Account Info ===")
    print(f"Login: {account_info.login}")
    print(f"Server: {account_info.server}")
    print(f"Balance: {account_info.balance}")
    print(f"Equity: {account_info.equity}")
    print(f"Margin: {account_info.margin}")
    print(f"Free Margin: {account_info.margin_free}")
    print(f"Margin Level: {account_info.margin_level}")
    print(f"Leverage: {account_info.leverage}")
else:
    print("[FAIL] Failed to get account info")
    mt5.shutdown()
    sys.exit(1)

# Get positions
positions = mt5.positions_get()
if positions is None:
    print("\n[INFO] No positions found")
elif len(positions) == 0:
    print("\n[INFO] No open positions")
else:
    print(f"\n=== Positions ({len(positions)}) ===")
    for pos in positions:
        print(f"\nPosition #{pos.ticket}:")
        print(f"  Symbol: {pos.symbol}")
        print(f"  Type: {'BUY (Long)' if pos.type == 0 else 'SELL (Short)'}")
        print(f"  Volume: {pos.volume} lots")
        print(f"  Open Price: {pos.price_open}")
        print(f"  Current Price: {pos.price_current}")
        print(f"  Profit: {pos.profit}")
        print(f"  Swap: {pos.swap}")

        # Check all available attributes
        print(f"\n  Available attributes:")
        for attr in dir(pos):
            if not attr.startswith('_'):
                try:
                    value = getattr(pos, attr)
                    if not callable(value):
                        print(f"    {attr}: {value}")
                except:
                    pass

        # Calculate liquidation price using simplified formula
        leverage = account_info.leverage
        maintenance_rate = 0.005  # 0.5% for XAUUSD

        print(f"\n  === Liquidation Price Calculation ===")
        if pos.type == 0:  # Long
            liq_price = pos.price_open * (1 - 1/leverage + maintenance_rate)
            print(f"  Formula: {pos.price_open} × (1 - 1/{leverage} + {maintenance_rate})")
            print(f"  Calculated Long Liquidation: {liq_price:.2f}")
        else:  # Short
            liq_price = pos.price_open * (1 + 1/leverage - maintenance_rate)
            print(f"  Formula: {pos.price_open} × (1 + 1/{leverage} - {maintenance_rate})")
            print(f"  Calculated Short Liquidation: {liq_price:.2f}")

mt5.shutdown()
print("\n[OK] Test completed!")
