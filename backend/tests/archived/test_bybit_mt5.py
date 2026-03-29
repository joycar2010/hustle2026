"""Test Bybit MT5 connection using correct method"""
import MetaTrader5 as mt5
import sys

print("=== Bybit MT5 Connection Test ===")
print(f"MT5 Library Version: {mt5.__version__}")

# Step 1: Initialize MT5 (connect to terminal)
print("\n[Step 1] Initializing MT5 terminal...")
terminal_path = "C:/Program Files/MetaTrader 5/terminal64.exe"

if not mt5.initialize(path=terminal_path):
    error = mt5.last_error()
    print(f"[FAIL] MT5 initialization failed: {error}")
    print("\nTroubleshooting:")
    print("1. Check if MT5 terminal is running")
    print("2. Enable 'Allow DLL imports' in MT5: Tools > Options > Expert Advisors")
    print("3. Enable 'Allow algorithmic trading' in MT5")
    print("4. Restart MT5 terminal after changing settings")
    sys.exit(1)

print("[OK] MT5 terminal initialized successfully!")

# Step 2: Check if already logged in
print("\n[Step 2] Checking current account status...")
account_info = mt5.account_info()

if account_info is None:
    print("[INFO] No account logged in")
    print("\nPlease login manually in MT5 terminal:")
    print("1. File > Login to Trade Account")
    print("2. Enter your MT5 account ID (e.g., 3971962)")
    print("3. Enter password")
    print("4. Select server: Bybit-Live-2 (or Bybit-TradFi-Live)")
    mt5.shutdown()
    sys.exit(1)
else:
    print("[OK] Account already logged in!")
    print(f"  - Login: {account_info.login}")
    print(f"  - Server: {account_info.server}")
    print(f"  - Balance: {account_info.balance}")
    print(f"  - Equity: {account_info.equity}")
    print(f"  - Margin Free: {account_info.margin_free}")
    print(f"  - Leverage: {account_info.leverage}")

# Step 3: Check terminal info
print("\n[Step 3] Checking terminal status...")
terminal_info = mt5.terminal_info()
if terminal_info:
    print(f"[OK] Terminal connected: {terminal_info.connected}")
    print(f"  - Trade allowed: {terminal_info.trade_allowed}")
    print(f"  - Company: {terminal_info.company}")
else:
    print("[WARN] Could not get terminal info")

# Step 4: Test symbol access
print("\n[Step 4] Testing symbol access...")
test_symbols = ["XAUUSD+", "XAUUSD", "GOLD"]

for symbol in test_symbols:
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info:
        print(f"[OK] Symbol '{symbol}' found:")
        print(f"  - Bid: {symbol_info.bid}")
        print(f"  - Ask: {symbol_info.ask}")
        print(f"  - Spread: {symbol_info.spread}")
        print(f"  - Visible: {symbol_info.visible}")

        # Try to get tick data
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            print(f"  - Last price: {tick.last}")
            print(f"  - Time: {tick.time}")
        break
    else:
        print(f"[INFO] Symbol '{symbol}' not found")

# Step 5: Test positions
print("\n[Step 5] Checking open positions...")
positions = mt5.positions_get()
if positions is not None:
    print(f"[OK] Found {len(positions)} open position(s)")
    for pos in positions:
        print(f"  - Ticket: {pos.ticket}, Symbol: {pos.symbol}, Volume: {pos.volume}, Profit: {pos.profit}")
else:
    print("[INFO] No open positions or error getting positions")

# Cleanup
mt5.shutdown()
print("\n=== Test completed successfully! ===")
print("\nMT5 connection is working properly.")
print("You can now start the backend service.")
