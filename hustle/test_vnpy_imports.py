#!/usr/bin/env python3
"""
测试VeighNa导入
"""

import sys

# 为Python 3.8添加zoneinfo支持
try:
    import zoneinfo
except ImportError:
    import backports.zoneinfo
    sys.modules['zoneinfo'] = backports.zoneinfo
    print("✓ 添加了zoneinfo支持")

try:
    import vnpy
    print(f"✓ vnpy 导入成功，版本: {vnpy.__version__}")
except ImportError as e:
    print(f"✗ vnpy 导入失败: {e}")

try:
    import vnpy_binance
    print(f"✓ vnpy_binance 导入成功")
except ImportError as e:
    print(f"✗ vnpy_binance 导入失败: {e}")

try:
    import vnpy.bybit
    print(f"✓ vnpy.bybit 导入成功")
except ImportError as e:
    print(f"✗ vnpy.bybit 导入失败: {e}")

try:
    import vnpy.binance
    print(f"✓ vnpy.binance 导入成功")
except ImportError as e:
    print(f"✗ vnpy.binance 导入失败: {e}")

# 尝试列出vnpy的所有模块
print("\nvnpy模块列表:")
try:
    import pkgutil
    import vnpy
    for _, name, _ in pkgutil.iter_modules(vnpy.__path__):
        print(f"  - {name}")
except Exception as e:
    print(f"获取模块列表失败: {e}")