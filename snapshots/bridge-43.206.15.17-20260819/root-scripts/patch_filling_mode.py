#!/usr/bin/env python3
"""
修复 MT5 桥 filling mode 硬编码 IOC 导致 Exness 拒单 10030。
按 symbol_info.filling_mode 位掩码动态选择: IOC(2)优先(IC 现行为=零回归) → FOK(1) → RETURN。
3处修改: 下单(622)、单笔平仓(726)、批量平仓(775)。断言式: 每个锚点必须恰好匹配1次。
"""
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else r"D:\QHMT5\runtime\releases\v1\ic\app\main.py"

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

# ---- 1. 注入 helper(锚: _normalize_volume 定义前) ----
HELPER_ANCHOR = "def _normalize_volume(volume: float, sym_info) -> float:"
HELPER = '''def _pick_filling(sym_info):
    """按 symbol 支持的 filling 位掩码选模式: IOC 优先(IC 现行为, 零回归) -> FOK -> RETURN。
    修 Exness-MT5Trial5 XAUUSD 不支持 IOC 时硬编码致 retcode=10030 拒单。"""
    fm = getattr(sym_info, "filling_mode", 0) or 0
    if fm & 2:   # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    if fm & 1:   # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN

def _normalize_volume(volume: float, sym_info) -> float:'''

assert src.count(HELPER_ANCHOR) == 1, f"helper anchor x{src.count(HELPER_ANCHOR)}"
src = src.replace(HELPER_ANCHOR, HELPER, 1)

# ---- 2. 下单路径(市价分支) ----
A2 = """        trade_action = mt5.TRADE_ACTION_DEAL
        type_filling = mt5.ORDER_FILLING_IOC"""
R2 = """        trade_action = mt5.TRADE_ACTION_DEAL
        type_filling = _pick_filling(sym_info)"""
assert src.count(A2) == 1, f"order anchor x{src.count(A2)}"
src = src.replace(A2, R2, 1)

# ---- 3. 单笔平仓 ----
A3 = '''        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        raise HTTPException(500, f"Close failed: {mt5.last_error()}")'''
R3 = '''        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling(sym_info),
    }
    result = mt5.order_send(request)
    if result is None:
        raise HTTPException(500, f"Close failed: {mt5.last_error()}")'''
assert src.count(A3) == 1, f"close anchor x{src.count(A3)}"
src = src.replace(A3, R3, 1)

# ---- 4. 批量平仓 ----
A4 = '''            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(request)'''
R4 = '''            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": _pick_filling(sym_info),
        }
        res = mt5.order_send(request)'''
assert src.count(A4) == 1, f"close-all anchor x{src.count(A4)}"
src = src.replace(A4, R4, 1)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("PATCH-OK: 4 substitutions applied to", PATH)
