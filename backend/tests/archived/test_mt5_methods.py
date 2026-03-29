"""Test MT5 connection with different methods"""
import MetaTrader5 as mt5
import sys
import os

print("Testing MT5 connection...")
print(f"MT5 version: {mt5.__version__}")

# Method 1: Initialize without parameters
print("\n=== Method 1: Initialize without parameters ===")
if mt5.initialize():
    print("[OK] MT5 initialized successfully!")
    account_info = mt5.account_info()
    if account_info:
        print(f"[OK] Account: {account_info.login}, Server: {account_info.server}")
    mt5.shutdown()
else:
    error = mt5.last_error()
    print(f"[FAIL] Error: {error}")

# Method 2: Initialize with path only
print("\n=== Method 2: Initialize with terminal path ===")
terminal_path = "C:/Program Files/MetaTrader 5/terminal64.exe"
if os.path.exists(terminal_path):
    print(f"Terminal path exists: {terminal_path}")
    if mt5.initialize(path=terminal_path):
        print("[OK] MT5 initialized successfully!")
        account_info = mt5.account_info()
        if account_info:
            print(f"[OK] Account: {account_info.login}, Server: {account_info.server}")
        mt5.shutdown()
    else:
        error = mt5.last_error()
        print(f"[FAIL] Error: {error}")
else:
    print(f"[FAIL] Terminal path not found: {terminal_path}")

# Method 3: Initialize with portable mode
print("\n=== Method 3: Initialize with portable flag ===")
if mt5.initialize(portable=True):
    print("[OK] MT5 initialized successfully!")
    account_info = mt5.account_info()
    if account_info:
        print(f"[OK] Account: {account_info.login}, Server: {account_info.server}")
    mt5.shutdown()
else:
    error = mt5.last_error()
    print(f"[FAIL] Error: {error}")

print("\n=== Test completed ===")
