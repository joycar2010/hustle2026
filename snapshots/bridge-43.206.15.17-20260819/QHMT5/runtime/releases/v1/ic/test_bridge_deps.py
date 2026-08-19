import MetaTrader5 as mt5
import redis

print("=== Test 1: MT5 Connection ===")
if mt5.initialize():
    print("OK MT5 initialized successfully")

    tick = mt5.symbol_info_tick('XAUUSD')
    if tick:
        print(f"OK XAUUSD tick: bid={tick.bid}, ask={tick.ask}, time={tick.time}")
    else:
        print("FAIL Failed to get XAUUSD tick")

    mt5.shutdown()
else:
    print("FAIL MT5 initialization failed")

print("\n=== Test 2: Redis Connection ===")
try:
    r = redis.Redis(host='127.0.0.1', port=6379, db=3, decode_responses=True)
    if r.ping():
        print("OK Redis connected successfully")

        # Test write
        r.hset('test:key', mapping={'field1': 'value1'})
        result = r.hgetall('test:key')
        print(f"OK Redis write/read test: {result}")
        r.delete('test:key')
    else:
        print("FAIL Redis ping failed")
except Exception as e:
    print(f"FAIL Redis error: {e}")

print("\n=== Test Complete ===")
