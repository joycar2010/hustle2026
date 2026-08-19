#!/usr/bin/env python3
"""
P0-B 补丁: STATE_STALE_SEC 单一值拆分为按数据类型的TTL (Windows路径版)
"""
import sys, py_compile

FB_PATH = r"D:\MT4LAB\agent\filebridge.py"

with open(FB_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

# --- 替换 STATE_STALE_SEC 单一值为多值 ---
OLD = "STATE_STALE_SEC = 3600.0  # P0-fix: hold EA state through reconnect"
NEW = """# P0-B: 按数据类型拆分 TTL (替代临时 STATE_STALE_SEC=3600)
STALE_HEARTBEAT_SEC  = 15.0    # EA/agent heartbeat
STALE_QUOTE_SEC      = 1.0     # tick 行情
STALE_POSITIONS_SEC  = 5.0     # 持仓快照
STALE_ACCOUNT_SEC    = 10.0    # 账户权益/保证金
STALE_SYMBOLS_SEC    = 1800.0  # 合约规格(digits/point)
STATE_STALE_SEC      = STALE_HEARTBEAT_SEC  # 向后兼容"""

assert src.count(OLD) == 1, f"anchor x{src.count(OLD)}: not found"
src = src.replace(OLD, NEW, 1)

# --- 增加 per-type is_fresh_for 方法 ---
OLD_FRESH = """    def is_fresh(self, age) -> bool:
        return age is not None and age <= STATE_STALE_SEC"""

NEW_FRESH = """    def is_fresh(self, age) -> bool:
        return age is not None and age <= STATE_STALE_SEC

    def is_fresh_for(self, age, data_type: str) -> bool:
        \"\"\"P0-B: 按数据类型判断新鲜度。data_type: heartbeat|quote|positions|account|symbols\"\"\"
        ttl_map = {
            'heartbeat': STALE_HEARTBEAT_SEC,
            'quote':     STALE_QUOTE_SEC,
            'positions': STALE_POSITIONS_SEC,
            'account':   STALE_ACCOUNT_SEC,
            'symbols':   STALE_SYMBOLS_SEC,
        }
        return age is not None and age <= ttl_map.get(data_type, STATE_STALE_SEC)"""

assert src.count(OLD_FRESH) == 1, f"fresh anchor x{src.count(OLD_FRESH)}"
src = src.replace(OLD_FRESH, NEW_FRESH, 1)

with open(FB_PATH, 'w', encoding='utf-8') as f:
    f.write(src)

py_compile.compile(FB_PATH, doraise=True)
print("OK filebridge.py STATE_STALE_SEC split to per-type TTL")
print("  HEARTBEAT=15s QUOTE=1s POSITIONS=5s ACCOUNT=10s SYMBOLS=1800s")
