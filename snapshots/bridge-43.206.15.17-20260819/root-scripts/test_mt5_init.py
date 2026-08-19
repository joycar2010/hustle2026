import MetaTrader5 as mt5
import os

print("=== MT5 Initialize Test ===")

# Test 1: Default initialize
print("\n[Test 1] mt5.initialize()")
result1 = mt5.initialize()
if result1:
    print("  SUCCESS")
    version = mt5.version()
    print(f"  Version: {version}")

    info = mt5.terminal_info()
    if info:
        print(f"  Terminal: {info.name}")
        print(f"  Path: {info.path}")
        print(f"  Connected: {info.connected}")

    mt5.shutdown()
else:
    error = mt5.last_error()
    print(f"  FAILED: {error}")

# Test 2: Common paths
print("\n[Test 2] Try common MT5 paths")
paths = [
    r"C:\Program Files\MetaTrader 5",
    r"C:\Program Files (x86)\MetaTrader 5",
    r"D:\MetaTrader 5",
    r"C:\MT5"
]

for path in paths:
    if os.path.exists(path):
        print(f"\n  Testing: {path}")
        if mt5.initialize(path=path):
            print(f"    SUCCESS with {path}")
            mt5.shutdown()
            break
        else:
            error = mt5.last_error()
            print(f"    FAILED: {error}")

print("\n=== Test Complete ===")
