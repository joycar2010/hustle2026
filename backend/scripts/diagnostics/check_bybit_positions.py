# -*- coding: utf-8 -*-
"""Diagnostic script to check Bybit MT5 positions"""
import asyncio
import sys
sys.path.insert(0, 'c:/app/hustle2026/backend')

from app.services.market_service import market_data_service

async def check_positions():
    mt5_client = market_data_service.mt5_client

    if not mt5_client.ensure_connection():
        print("[ERROR] MT5 connection failed")
        return

    print("[OK] MT5 connected")
    print("\n" + "="*60)
    print("Checking XAUUSD+ positions")
    print("="*60)

    positions = mt5_client.get_positions("XAUUSD+")

    if not positions:
        print("[WARNING] No XAUUSD+ positions found")
    else:
        print(f"\nFound {len(positions)} position(s):\n")
        for i, pos in enumerate(positions, 1):
            pos_type = "LONG (BUY)" if pos['type'] == 0 else "SHORT (SELL)"
            print(f"Position #{i}:")
            print(f"  Ticket: {pos['ticket']}")
            print(f"  Type: {pos_type}")
            print(f"  Volume: {pos['volume']} Lot")
            print(f"  Open Price: {pos['price_open']}")
            print(f"  Current Price: {pos['price_current']}")
            print(f"  Profit: ${pos['profit']:.2f}")
            print()

    print("="*60)
    print("Testing find_position_to_close method")
    print("="*60)

    print("\n1. Find SHORT position (for forward closing):")
    short_ticket = mt5_client.find_position_to_close("XAUUSD+", "Buy")
    if short_ticket:
        print(f"   [OK] Found SHORT position: ticket={short_ticket}")
    else:
        print(f"   [ERROR] No SHORT position found")

    print("\n2. Find LONG position (for reverse closing):")
    long_ticket = mt5_client.find_position_to_close("XAUUSD+", "Sell")
    if long_ticket:
        print(f"   [OK] Found LONG position: ticket={long_ticket}")
    else:
        print(f"   [ERROR] No LONG position found")

    print("\n" + "="*60)

if __name__ == "__main__":
    asyncio.run(check_positions())
