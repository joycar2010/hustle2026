"""Trading time validation utilities"""
from datetime import datetime, timezone


def is_bybit_trading_hours() -> tuple[bool, str]:
    """
    Check if Bybit MT5 is currently in trading hours.

    Bybit MT5 trading hours:
    - Weekdays: 01:00 - 23:59 UTC (Monday 01:00 to Friday 23:59)
    - Weekend: Closed (Saturday 00:00 to Sunday 23:59)

    Returns:
        tuple: (is_open: bool, message: str)
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    hour = now.hour

    # Saturday (5) and Sunday (6) are closed
    if weekday == 5:  # Saturday
        return False, "Bybit MT5休市中（周六全天休市）"
    elif weekday == 6:  # Sunday
        return False, "Bybit MT5休市中（周日全天休市）"

    # Monday 00:00-00:59 is closed (opens at 01:00)
    if weekday == 0 and hour < 1:
        return False, "Bybit MT5休市中（周一01:00 UTC开市）"

    # Friday 23:59 onwards is closed
    if weekday == 4 and hour >= 23:
        return False, "Bybit MT5即将休市（周五23:59 UTC休市）"

    return True, "Bybit MT5交易时间"


def get_bybit_next_open_time() -> str:
    """
    Get the next opening time for Bybit MT5.

    Returns:
        str: Human-readable next opening time
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()

    if weekday == 5:  # Saturday
        return "下周一 01:00 UTC"
    elif weekday == 6:  # Sunday
        return "明天 01:00 UTC"
    elif weekday == 0 and now.hour < 1:  # Monday before 01:00
        return "今天 01:00 UTC"
    elif weekday == 4 and now.hour >= 23:  # Friday after 23:00
        return "下周一 01:00 UTC"

    return "当前为交易时间"
