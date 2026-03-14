#!/usr/bin/env python
"""测试价格精度问题"""

# 模拟浮点数精度问题
bid_price = 5174.28
buy_price_raw = bid_price + 0.01
buy_price_rounded = round(bid_price + 0.01, 2)

print(f"=== 价格计算测试 ===")
print(f"原始 bid_price: {bid_price}")
print(f"计算 bid_price + 0.01 (未四舍五入): {buy_price_raw}")
print(f"计算 round(bid_price + 0.01, 2): {buy_price_rounded}")
print(f"")
print(f"精度检查:")
print(f"  buy_price_raw == buy_price_rounded: {buy_price_raw == buy_price_rounded}")
print(f"  buy_price_raw 小数位数: {len(str(buy_price_raw).split('.')[-1])}")
print(f"  buy_price_rounded 小数位数: {len(str(buy_price_rounded).split('.')[-1])}")
print(f"")

# 测试字符串转换
price_str = str(buy_price_rounded)
price_from_str = float(price_str)
print(f"字符串转换测试:")
print(f"  str(buy_price_rounded): '{price_str}'")
print(f"  float('{price_str}'): {price_from_str}")
print(f"  round(float('{price_str}'), 2): {round(price_from_str, 2)}")
print(f"")

# 测试 MT5 可能的问题
print(f"MT5 价格格式测试:")
print(f"  价格值: {buy_price_rounded}")
print(f"  类型: {type(buy_price_rounded)}")
print(f"  是否为 2 位小数: {round(buy_price_rounded, 2) == buy_price_rounded}")
