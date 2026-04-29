"""
时间工具模块 - UTC标准化工具函数
用途：提供统一的UTC时间处理函数，确保全系统时间一致性
作者：系统架构团队
版本：1.0.0
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# MT5 broker servers use EET/EEST (UTC+2 winter, UTC+3 summer)
_MT5_SERVER_TZ = ZoneInfo("Europe/Helsinki")


def mt5_server_ts_to_utc(raw_ts: int) -> int:
    """Convert MT5 bridge deal.time (broker server local time) to UTC Unix timestamp.

    MT5 deal.time is a Unix-like timestamp encoded in broker server timezone (EET/EEST),
    not UTC. This function converts it to a true UTC timestamp, handling DST automatically.
    """
    naive = datetime.utcfromtimestamp(raw_ts)
    local = naive.replace(tzinfo=_MT5_SERVER_TZ)
    return int(local.astimezone(timezone.utc).timestamp())


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
    """MT5时间戳 → 北京时间字符串（DST-aware）

    MT5 deal.time 是 broker server local time (EET/EEST) 编码的 Unix-like 时间戳。
    通过 zoneinfo 自动处理夏令时（UTC+2 冬 / UTC+3 夏）。
    """
    utc_ts = mt5_server_ts_to_utc(mt5_timestamp)
    utc_dt = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
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
