import MetaTrader5 as mt5
import sys
import os

print("=== MT5 Detailed Test ===")
print(f"Python: {sys.version}")
print(f"MT5 module: {mt5.__file__}")
print()

# Test with the actual path from process
mt5_path = r"D:\QHCELL\pool\m2\terminal\terminal.exe"
print(f"Testing with path: {mt5_path}")
print(f"File exists: {os.path.exists(mt5_path)}")
print()

# Try initialize
print("Attempting mt5.initialize()...")
result = mt5.initialize(path=mt5_path, portable=True)

if result:
    print("SUCCESS!")
    print()

    # Get terminal info
    info = mt5.terminal_info()
    if info:
        print(f"Terminal Info:")
        print(f"  Name: {info.name}")
        print(f"  Path: {info.path}")
        print(f"  Connected: {info.connected}")
        print(f"  Trade Allowed: {info.trade_allowed}")

    # Try to get a tick
    print()
    print("Testing tick query for XAUUSD...")
    tick = mt5.symbol_info_tick('XAUUSD')
    if tick:
        print(f"  SUCCESS: bid={tick.bid}, ask={tick.ask}")
    else:
        print(f"  FAILED: {mt5.last_error()}")

    mt5.shutdown()
else:
    error = mt5.last_error()
    print(f"FAILED: {error}")
    print()
    print("Trying without portable flag...")

    result2 = mt5.initialize(path=mt5_path)
    if result2:
        print("SUCCESS without portable!")
        mt5.shutdown()
    else:
        error2 = mt5.last_error()
        print(f"FAILED again: {error2}")

print()
print("=== Test Complete ===")
