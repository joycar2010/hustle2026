"""Test MT5 connection"""
import MetaTrader5 as mt5
import sys

print("Testing MT5 connection...")
print(f"MT5 version: {mt5.__version__}")

# Try to initialize without credentials (use already logged in terminal)
print("\n1. Trying to initialize without credentials...")
if mt5.initialize():
    print("[OK] MT5 initialized successfully!")

    # Get account info
    account_info = mt5.account_info()
    if account_info:
        print(f"[OK] Account info retrieved:")
        print(f"  - Login: {account_info.login}")
        print(f"  - Server: {account_info.server}")
        print(f"  - Balance: {account_info.balance}")
        print(f"  - Equity: {account_info.equity}")
    else:
        print("[FAIL] Failed to get account info")

    # Get terminal info
    terminal_info = mt5.terminal_info()
    if terminal_info:
        print(f"[OK] Terminal info:")
        print(f"  - Connected: {terminal_info.connected}")
        print(f"  - Trade allowed: {terminal_info.trade_allowed}")

    # Test symbol
    symbol = "XAUUSD+"
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info:
        print(f"[OK] Symbol {symbol} found:")
        print(f"  - Bid: {symbol_info.bid}")
        print(f"  - Ask: {symbol_info.ask}")
        print(f"  - Visible: {symbol_info.visible}")
    else:
        print(f"[FAIL] Symbol {symbol} not found")

    mt5.shutdown()
    print("\n[OK] MT5 connection test successful!")
    sys.exit(0)
else:
    error = mt5.last_error()
    print(f"[FAIL] MT5 initialization failed: {error}")
    sys.exit(1)
