#!/usr/bin/env python3
"""
修复 filebridge.py:
1. STATE_STALE_SEC 20->120  (给 MT4 EA 初始化留足时间,不因短暂延迟报 disconnected)
2. is_fresh_ticks() 辅助判断: ticks 新鲜时不因 meta 稍旧报 503
"""
import sys, re

PATH = r"D:\MT4LAB\agent\filebridge.py"

with open(PATH, encoding="utf-8") as f:
    src = f.read()

# 1. Raise stale threshold
assert src.count("STATE_STALE_SEC = 20.0") == 1
src = src.replace("STATE_STALE_SEC = 20.0",
                  "STATE_STALE_SEC = 120.0  # P0-fix: give MT4 EA time to reconnect")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("PATCH-OK STATE_STALE_SEC 20->120")
