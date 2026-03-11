"""Test MT5 order book functionality"""
import MetaTrader5 as mt5
import sys
sys.path.insert(0, 'C:/app/hustle2026/backend')

from app.core.config import settings
from app.services.mt5_client import MT5Client

# Initialize MT5 client
mt5_client = MT5Client(
    login=int(settings.BYBIT_MT5_ID),
    password=settings.BYBIT_MT5_PASSWORD,
    server=settings.BYBIT_MT5_SERVER
)

print("Connecting to MT5...")
if mt5_client.connect():
    print("[OK] MT5 connected successfully")

    symbol = "XAUUSD.s"
    print(f"\nTesting order book for {symbol}...")

    # Test market_book_get
    book = mt5.market_book_get(symbol)
    if book is None:
        error = mt5.last_error()
        print(f"[FAIL] market_book_get failed: {error}")

        # Try to subscribe first
        print(f"\nTrying to subscribe to market book...")
        if mt5.market_book_add(symbol):
            print(f"[OK] Subscribed to market book for {symbol}")

            # Try again
            book = mt5.market_book_get(symbol)
            if book is None:
                print(f"[FAIL] Still failed: {mt5.last_error()}")
            else:
                print(f"[OK] Got order book data: {len(book)} entries")
        else:
            print(f"[FAIL] Failed to subscribe: {mt5.last_error()}")
    else:
        print(f"[OK] Got order book data: {len(book)} entries")

        if book:
            print("\nOrder book entries:")
            for i, entry in enumerate(book[:5]):  # Show first 5 entries
                print(f"  {i+1}. Type: {entry.type}, Price: {entry.price}, Volume: {entry.volume}")

            # Test the filtering logic
            bid_book = [b for b in book if b.type == mt5.BOOK_TYPE_BUY]
            ask_book = [b for b in book if b.type == mt5.BOOK_TYPE_SELL]

            print(f"\nFiltered results:")
            print(f"  BID entries (BOOK_TYPE_BUY={mt5.BOOK_TYPE_BUY}): {len(bid_book)}")
            print(f"  ASK entries (BOOK_TYPE_SELL={mt5.BOOK_TYPE_SELL}): {len(ask_book)}")

            if bid_book:
                bid_best = max(bid_book, key=lambda x: x.price)
                print(f"  Best BID: {bid_best.price} (volume: {bid_best.volume})")

            if ask_book:
                ask_best = min(ask_book, key=lambda x: x.price)
                print(f"  Best ASK: {ask_best.price} (volume: {ask_best.volume})")

    # Test using the client method
    print("\n\nTesting mt5_client.get_market_book()...")
    result = mt5_client.get_market_book(symbol)
    if result:
        print(f"[OK] Success:")
        print(f"  BID: {result['bid_price']} (volume: {result['bid_volume']})")
        print(f"  ASK: {result['ask_price']} (volume: {result['ask_volume']})")
    else:
        print("[FAIL] Failed to get market book")

    mt5_client.disconnect()
else:
    print("[FAIL] Failed to connect to MT5")
