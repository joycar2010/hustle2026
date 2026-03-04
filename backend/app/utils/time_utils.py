"""
时间工具模块 - UTC标准化工具函数
用途：提供统一的UTC时间处理函数，确保全系统时间一致性
作者：系统架构团队
版本：1.0.0
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """
    获取当前UTC时间（naive datetime，与数据库TIMESTAMP WITHOUT TIME ZONE兼容）

    Returns:
        datetime: 当前UTC时间（无时区信息）

    Example:
        >>> now = utc_now()
        >>> print(now)
        2026-02-24 10:30:00.123456
    """
    return datetime.utcnow()


def utc_now_aware() -> datetime:
    """
    获取当前UTC时间（aware datetime，包含时区信息）

    Returns:
        datetime: 当前UTC时间（包含UTC时区信息）

    Example:
        >>> now = utc_now_aware()
        >>> print(now)
        2026-02-24 10:30:00.123456+00:00
    """
    return datetime.now(timezone.utc)


def format_utc_time(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化UTC时间为ISO 8601格式（含时区标识）

    Args:
        dt: datetime对象（可以是naive或aware）

    Returns:
        str: ISO 8601格式的时间字符串，如 "2026-02-24T10:30:00Z"
        None: 如果输入为None

    Example:
        >>> dt = datetime(2026, 2, 24, 10, 30, 0)
        >>> format_utc_time(dt)
        '2026-02-24T10:30:00Z'
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Naive datetime，假设为UTC
        return dt.isoformat() + "Z"
    else:
        # Aware datetime，转换为UTC
        utc_dt = dt.astimezone(timezone.utc)
        return utc_dt.isoformat().replace('+00:00', 'Z')


def parse_utc_time(time_str: str) -> datetime:
    """
    解析ISO 8601格式的UTC时间字符串

    Args:
        time_str: ISO 8601格式的时间字符串

    Returns:
        datetime: UTC时间（naive datetime，与数据库兼容）

    Example:
        >>> parse_utc_time("2026-02-24T10:30:00Z")
        datetime(2026, 2, 24, 10, 30, 0)

        >>> parse_utc_time("2026-02-24T10:30:00+00:00")
        datetime(2026, 2, 24, 10, 30, 0)
    """
    # 处理Z结尾的时间字符串
    if time_str.endswith('Z'):
        time_str = time_str[:-1] + '+00:00'

    # 解析为aware datetime
    dt = datetime.fromisoformat(time_str)

    # 转换为UTC并移除时区信息（与数据库TIMESTAMP WITHOUT TIME ZONE兼容）
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def to_timestamp_ms(dt: datetime) -> int:
    """
    转换datetime为Unix时间戳（毫秒）

    Args:
        dt: datetime对象

    Returns:
        int: Unix时间戳（毫秒）

    Example:
        >>> dt = datetime(2026, 2, 24, 10, 30, 0)
        >>> to_timestamp_ms(dt)
        1740394200000
    """
    if dt.tzinfo is None:
        # Naive datetime，假设为UTC
        dt = dt.replace(tzinfo=timezone.utc)

    return int(dt.timestamp() * 1000)


def from_timestamp_ms(ts: int) -> datetime:
    """
    从Unix时间戳（毫秒）转换为UTC时间

    Args:
        ts: Unix时间戳（毫秒）

    Returns:
        datetime: UTC时间（naive datetime）

    Example:
        >>> from_timestamp_ms(1740394200000)
        datetime(2026, 2, 24, 10, 30, 0)
    """
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)


def today_start_utc() -> datetime:
    """
    获取今日UTC时间的开始时刻（00:00:00）

    Returns:
        datetime: 今日UTC时间的开始时刻

    Example:
        >>> today_start_utc()
        datetime(2026, 2, 24, 0, 0, 0)
    """
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def today_end_utc() -> datetime:
    """
    获取今日UTC时间的结束时刻（23:59:59.999999）

    Returns:
        datetime: 今日UTC时间的结束时刻

    Example:
        >>> today_end_utc()
        datetime(2026, 2, 24, 23, 59, 59, 999999)
    """
    return datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)


def format_log_time(dt: Optional[datetime] = None) -> str:
    """
    格式化时间为日志友好格式

    Args:
        dt: datetime对象，如果为None则使用当前UTC时间

    Returns:
        str: 格式化的时间字符串，如 "2026-02-24 10:30:00 UTC"

    Example:
        >>> format_log_time()
        '2026-02-24 10:30:00 UTC'
    """
    if dt is None:
        dt = datetime.utcnow()

    return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def format_filename_time(dt: Optional[datetime] = None) -> str:
    """
    格式化时间为文件名友好格式（用于备份文件等）

    Args:
        dt: datetime对象，如果为None则使用当前UTC时间

    Returns:
        str: 格式化的时间字符串，如 "20260224_103000_UTC"

    Example:
        >>> format_filename_time()
        '20260224_103000_UTC'
    """
    if dt is None:
        dt = datetime.utcnow()

    return dt.strftime("%Y%m%d_%H%M%S") + "_UTC"


# 向后兼容的别名
get_utc_now = utc_now
format_iso_time = format_utc_time
parse_iso_time = parse_utc_time


# ============================================================================
# 北京时间转换函数（用于交易历史统一显示）
# ============================================================================

def beijing_to_utc_ms(beijing_time_str: str) -> int:
    """
    北京时间字符串 → UTC毫秒时间戳

    Args:
        beijing_time_str: 北京时间字符串，格式：YYYY-MM-DD HH:MM:SS

    Returns:
        UTC毫秒时间戳

    Example:
        >>> beijing_to_utc_ms("2026-03-04 23:20:11")
        # 对应 2026-03-04 15:20:11 UTC
    """
    from datetime import timedelta
    dt = datetime.strptime(beijing_time_str, "%Y-%m-%d %H:%M:%S")
    # 北京时间 = UTC + 8小时，所以 UTC = 北京时间 - 8小时
    utc_dt = dt - timedelta(hours=8)
    return int(utc_dt.timestamp() * 1000)


def utc_ms_to_beijing(timestamp_ms: int) -> str:
    """
    UTC毫秒时间戳 → 北京时间字符串

    Args:
        timestamp_ms: UTC毫秒时间戳

    Returns:
        北京时间字符串，格式：YYYY-MM-DD HH:MM:SS

    Example:
        >>> utc_ms_to_beijing(1709582411000)
        "2026-03-04 23:20:11"
    """
    from datetime import timedelta
    utc_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    # 北京时间 = UTC + 8小时
    beijing_dt = utc_dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")


def mt5_time_to_beijing(mt5_timestamp: int) -> str:
    """
    MT5时间戳 → 北京时间字符串

    MT5返回的时间戳需要特殊处理：
    - MT5的时间戳是服务器时间（UTC+2）的Unix时间戳
    - 需要减去2小时得到真实UTC时间
    - 再加8小时得到北京时间
    - 总共是 +6小时

    Args:
        mt5_timestamp: MT5 Unix时间戳

    Returns:
        北京时间字符串，格式：YYYY-MM-DD HH:MM:SS

    Example:
        >>> mt5_time_to_beijing(1709575151)
        "2024-03-05 00:59:11"  # 北京时间
    """
    from datetime import timedelta
    # MT5时间戳转为datetime（假设为UTC）
    mt5_dt = datetime.fromtimestamp(mt5_timestamp, tz=timezone.utc)
    # 减去2小时得到真实UTC时间（因为MT5服务器是UTC+2）
    utc_dt = mt5_dt - timedelta(hours=2)
    # 加8小时得到北京时间
    beijing_dt = utc_dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")


def utc_datetime_to_beijing(utc_dt: datetime) -> str:
    """
    UTC datetime对象 → 北京时间字符串

    Args:
        utc_dt: UTC datetime对象

    Returns:
        北京时间字符串，格式：YYYY-MM-DD HH:MM:SS
    """
    from datetime import timedelta
    beijing_dt = utc_dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")


def beijing_to_utc_datetime(beijing_time_str: str) -> datetime:
    """
    北京时间字符串 → UTC datetime对象

    Args:
        beijing_time_str: 北京时间字符串，格式：YYYY-MM-DD HH:MM:SS

    Returns:
        UTC datetime对象
    """
    from datetime import timedelta
    dt = datetime.strptime(beijing_time_str, "%Y-%m-%d %H:%M:%S")
    utc_dt = dt - timedelta(hours=8)
    return utc_dt.replace(tzinfo=timezone.utc)
