"""Bybit MT5 symbol configuration for accurate liquidation price calculation"""

# Bybit MT5 品种参数配置（精准匹配 Bybit 官方值）
BYBIT_MT5_SYMBOL_CONFIG = {
    "XAUUSD.s": {
        "contract_unit": 100,          # 1手=100盎司
        "margin_rate_initial": 0.01,   # 初始保证金率1%
        "margin_rate_maintenance": 0.005,  # 维持保证金率0.5%（爆仓触发阈值）
        "digits": 2                    # 价格精度
    },
    "XAUUSD": {
        "contract_unit": 100,
        "margin_rate_initial": 0.01,
        "margin_rate_maintenance": 0.005,
        "digits": 2
    },
    "BTCUSD": {
        "contract_unit": 1,            # 1手=1 BTC
        "margin_rate_initial": 0.01,
        "margin_rate_maintenance": 0.005,
        "digits": 1
    },
    "ETHUSD": {
        "contract_unit": 1,
        "margin_rate_initial": 0.01,
        "margin_rate_maintenance": 0.005,
        "digits": 2
    },
    "US30": {
        "contract_unit": 1,            # 1手=1点
        "margin_rate_initial": 0.01,
        "margin_rate_maintenance": 0.005,
        "digits": 2
    }
}


def get_symbol_config(symbol: str) -> dict:
    """
    Get symbol configuration for liquidation price calculation

    Args:
        symbol: Trading symbol (e.g., "XAUUSD.s")

    Returns:
        Symbol configuration dict with contract_unit, margin rates, and digits
    """
    # Try exact match first
    if symbol in BYBIT_MT5_SYMBOL_CONFIG:
        return BYBIT_MT5_SYMBOL_CONFIG[symbol]

    # Try without suffix (e.g., "XAUUSD.s" -> "XAUUSD")
    base_symbol = symbol.split('.')[0]
    if base_symbol in BYBIT_MT5_SYMBOL_CONFIG:
        return BYBIT_MT5_SYMBOL_CONFIG[base_symbol]

    # Default fallback configuration
    return {
        "contract_unit": 1,
        "margin_rate_initial": 0.01,
        "margin_rate_maintenance": 0.005,
        "digits": 2
    }
