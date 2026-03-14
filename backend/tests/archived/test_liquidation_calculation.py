"""Test script to verify Bybit MT5 liquidation price calculation"""
import MetaTrader5 as mt5
import os
from dotenv import load_dotenv
import sys

# Set UTF-8 encoding for console output
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core.bybit_mt5_config import get_symbol_config

# Load configuration
load_dotenv()
MT5_ACCOUNT = int(os.getenv("BYBIT_MT5_ID", "3971962"))
MT5_PASSWORD = os.getenv("BYBIT_MT5_PASSWORD", "Aq987456!")
MT5_SERVER = os.getenv("BYBIT_MT5_SERVER", "Bybit-Live-2")
MT5_PATH = os.getenv("MT5_PATH", "C:/Program Files/MetaTrader 5/terminal64.exe")

print(f"Connecting to MT5...")
print(f"Account: {MT5_ACCOUNT}")
print(f"Server: {MT5_SERVER}\n")

# Initialize and login
if not mt5.initialize(MT5_PATH):
    print(f"MT5 initialize failed: {mt5.last_error()}")
    sys.exit(1)

if not mt5.login(MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER):
    print(f"MT5 login failed: {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print("MT5 login successful\n")

# Get account info
account = mt5.account_info()
if not account:
    print("Failed to get account info")
    mt5.shutdown()
    sys.exit(1)

print("=" * 80)
print("ACCOUNT INFORMATION")
print("=" * 80)
print(f"Balance: {account.balance:.2f}")
print(f"Equity: {account.equity:.2f}")
print(f"Margin: {account.margin:.2f}")
print(f"Free Margin: {account.margin_free:.2f}")
print(f"Margin Level: {account.margin_level:.2f}%")
print(f"Leverage: {account.leverage}x\n")

# Get positions
positions = mt5.positions_get()
if not positions:
    print("No positions found")
    mt5.shutdown()
    sys.exit(0)

print("=" * 80)
print(f"POSITIONS ({len(positions)} found)")
print("=" * 80)

for i, pos in enumerate(positions, 1):
    symbol = pos.symbol
    pos_type = pos.type  # 0=Long, 1=Short
    volume = pos.volume
    price_open = pos.price_open
    price_current = pos.price_current
    profit = pos.profit
    margin = getattr(pos, 'margin', 0.0)

    # Get symbol configuration
    symbol_config = get_symbol_config(symbol)
    contract_unit = symbol_config["contract_unit"]
    margin_rate_initial = symbol_config["margin_rate_initial"]
    margin_rate_maintenance = symbol_config["margin_rate_maintenance"]
    digits = symbol_config["digits"]

    print(f"\n--- Position {i}: {symbol} ---")
    print(f"Type: {'LONG' if pos_type == 0 else 'SHORT'}")
    print(f"Volume: {volume} lots")
    print(f"Open Price: {price_open:.{digits}f}")
    print(f"Current Price: {price_current:.{digits}f}")
    print(f"Profit: {profit:.2f}")
    print(f"Position Margin: {margin:.2f}")

    # Check for native liquidation price
    native_liq_price = getattr(pos, 'price_liquidation', 0.0)
    if native_liq_price > 0:
        print(f"Native Liquidation Price: {native_liq_price:.{digits}f}")
    else:
        print("Native Liquidation Price: Not available")

    # Calculate liquidation price manually
    print(f"\n--- Manual Calculation ---")
    print(f"Contract Unit: {contract_unit}")
    print(f"Initial Margin Rate: {margin_rate_initial * 100}%")
    print(f"Maintenance Margin Rate: {margin_rate_maintenance * 100}%")
    print(f"Account Leverage: {account.leverage}x")

    # Calculate position margin (since MT5 pos.margin may be 0)
    if account.leverage > 0:
        position_margin = (price_open * volume * contract_unit) / account.leverage
    else:
        position_margin = 0
    print(f"Position Margin (calculated): {position_margin:.2f}")

    # Calculate maintenance margin
    if position_margin > 0 and margin_rate_initial > 0:
        maintenance_margin = position_margin * (margin_rate_maintenance / margin_rate_initial)
    else:
        maintenance_margin = 0
    print(f"Maintenance Margin: {maintenance_margin:.2f}")

    # Calculate unrealized PnL
    if pos_type == 0:  # Long
        unrealized_pnl = (price_current - price_open) * volume * contract_unit
    else:  # Short
        unrealized_pnl = (price_open - price_current) * volume * contract_unit
    print(f"Unrealized PnL: {unrealized_pnl:.2f}")

    # Calculate liquidation price using Bybit simplified formula
    # This formula assumes isolated margin mode
    print(f"\n--- Bybit Simplified Formula ---")
    if pos_type == 0:  # Long
        # 多头强平价 = 开仓价 × (1 - 1/杠杆 + 维持保证金率)
        liquidation_price = price_open * (1 - 1/account.leverage + margin_rate_maintenance)
        formula = f"{price_open:.{digits}f} × (1 - 1/{account.leverage} + {margin_rate_maintenance})"
    else:  # Short
        # 空头强平价 = 开仓价 × (1 + 1/杠杆 - 维持保证金率)
        liquidation_price = price_open * (1 + 1/account.leverage - margin_rate_maintenance)
        formula = f"{price_open:.{digits}f} × (1 + 1/{account.leverage} - {margin_rate_maintenance})"

    print(f"Formula: {formula}")
    print(f"Calculated Liquidation Price: {liquidation_price:.{digits}f}")

    # Calculate distance to liquidation
    if pos_type == 0:  # Long
        distance = ((price_current - liquidation_price) / price_current) * 100
    else:  # Short
        distance = ((liquidation_price - price_current) / price_current) * 100
    print(f"Distance to Liquidation: {distance:.2f}%")

print("\n" + "=" * 80)
mt5.shutdown()
