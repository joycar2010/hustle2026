"""Trading time validation utilities

Bybit MT5 XAUUSD+ trading schedule (Beijing Time / UTC+8):
  Summer (Apr-Oct): Mon 06:00 ~ Sat 05:00
  Winter (Nov-Mar): Mon 07:00 ~ Sat 06:00

The saved config in config/market_closure.json stores these values.
"""
import json
import os
from datetime import datetime, timezone, timedelta

_BJT = timezone(timedelta(hours=8))
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'market_closure.json')

# Defaults (Beijing Time)
_DEFAULTS = {
    "enabled": True,
    "summer_open": "周一 06:00",
    "summer_close": "周六 05:00",
    "winter_open": "周一 07:00",
    "winter_close": "周六 06:00",
}


def _load_config() -> dict:
    """Load market closure config from JSON file, fall back to defaults."""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            if isinstance(cfg, dict) and "config" in cfg:
                cfg = cfg["config"]
            return {**_DEFAULTS, **cfg}
    except Exception:
        return dict(_DEFAULTS)


def _parse_weekday_hour(s: str) -> tuple[int, int]:
    """Parse '周一 06:00' → (weekday=0, hour=6). Returns (-1,-1) on error."""
    day_map = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}
    try:
        parts = s.strip().split()
        wd = day_map.get(parts[0], -1)
        h = int(parts[1].split(":")[0])
        return wd, h
    except Exception:
        return -1, -1


def _nth_sunday(year: int, month: int, n: int):
    """返回某年某月的第 n 个周日的 date 对象。"""
    from datetime import date
    d = date(year, month, 1)
    # weekday(): Mon=0..Sun=6。本月第一个周日的日号：
    first_sunday = 1 + (6 - d.weekday()) % 7
    return date(year, month, first_sunday + (n - 1) * 7)


def _is_summer(dt) -> bool:
    """夏令时判断（北京时间日期级）。

    规则（用户指定 / 美国夏令时）：
      夏令时：3月第二个周日 ~ 11月第一个周日
      冬令时：其余时间
    兼容旧调用：若传入 int(月份) 则退回粗略按月判断。
    """
    if isinstance(dt, int):
        return 4 <= dt <= 10  # 向后兼容（粗略）
    d = dt.date() if hasattr(dt, "date") else dt
    dst_start = _nth_sunday(d.year, 3, 2)   # 3月第二个周日
    dst_end   = _nth_sunday(d.year, 11, 1)  # 11月第一个周日
    return dst_start <= d < dst_end


def is_bybit_trading_hours() -> tuple[bool, str]:
    """
    Check if Bybit MT5 is currently in trading hours based on config.

    Returns:
        tuple: (is_open: bool, message: str)
    """
    cfg = _load_config()

    if not cfg.get("enabled", True):
        return True, "停市检测已关闭"

    now_bjt = datetime.now(_BJT)
    weekday = now_bjt.weekday()  # 0=Mon, 6=Sun
    hour = now_bjt.hour
    month = now_bjt.month

    summer = _is_summer(now_bjt)
    season_label = "夏令时" if summer else "冬令时"

    if summer:
        open_wd, open_h = _parse_weekday_hour(cfg.get("summer_open", _DEFAULTS["summer_open"]))
        close_wd, close_h = _parse_weekday_hour(cfg.get("summer_close", _DEFAULTS["summer_close"]))
    else:
        open_wd, open_h = _parse_weekday_hour(cfg.get("winter_open", _DEFAULTS["winter_open"]))
        close_wd, close_h = _parse_weekday_hour(cfg.get("winter_close", _DEFAULTS["winter_close"]))

    # Validate parsed values, fall back to hardcoded if parse failed
    if open_wd < 0 or close_wd < 0:
        open_wd, open_h = 0, 6 if summer else 7
        close_wd, close_h = 5, 5 if summer else 6

    # Saturday after close hour / Sunday = closed
    if weekday == 5 and hour >= close_h:
        return False, f"MT5休市中（{season_label}，周六{close_h:02d}:00后休市）"
    if weekday == 5 and close_wd == 5 and hour < close_h:
        # Saturday before close hour: still open
        if hour >= close_h - 1:
            return True, f"MT5即将休市（{season_label}，{close_h:02d}:00休市）"
        return True, f"MT5交易中（{season_label}）"
    if weekday == 6:  # Sunday - always closed
        return False, f"MT5休市中（{season_label}，周日全天休市）"

    # Monday before open hour = closed
    if weekday == open_wd and hour < open_h:
        return False, f"MT5休市中（{season_label}，周一{open_h:02d}:00开市）"

    # Friday approaching close (if close is Saturday 05:00, Friday is always open)
    # But warn 1 hour before Saturday close
    if weekday == 4 and close_wd == 5:
        # Close is Saturday, so Friday is fully open
        return True, f"MT5交易中（{season_label}）"

    # Normal trading hours
    return True, f"MT5交易中（{season_label}）"


def get_bybit_next_open_time() -> str:
    """Get the next opening time for Bybit MT5."""
    cfg = _load_config()
    now_bjt = datetime.now(_BJT)
    month = now_bjt.month
    summer = _is_summer(now_bjt)
    season = "夏令时" if summer else "冬令时"

    if summer:
        _, open_h = _parse_weekday_hour(cfg.get("summer_open", _DEFAULTS["summer_open"]))
    else:
        _, open_h = _parse_weekday_hour(cfg.get("winter_open", _DEFAULTS["winter_open"]))

    if open_h < 0:
        open_h = 6 if summer else 7

    weekday = now_bjt.weekday()

    if weekday == 5:
        return f"下周一 {open_h:02d}:00 北京时间（{season}）"
    elif weekday == 6:
        return f"明天 {open_h:02d}:00 北京时间（{season}）"
    elif weekday == 0 and now_bjt.hour < open_h:
        return f"今天 {open_h:02d}:00 北京时间（{season}）"

    return f"当前为交易时间（{season}）"


def get_next_mt5_close_dt():
    """返回下一次 MT5 休市的北京时间 datetime；若当前已休市或检测关闭则返回 None。

    Bybit MT5 服务器时区为 EET/EEST(UTC+2/+3)，每日 00:00 服务器时间有日级休市
    (rollover)，换算北京时间为 夏令时05:00 / 冬令时06:00（即配置 close_h 的小时）。
    每天该时刻都休市；周六那次为周末休市。因此"下一次休市"= 下一个 close_h:00。
    """
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return None
    is_open, _ = is_bybit_trading_hours()
    if not is_open:
        return None
    now = datetime.now(_BJT)
    summer = _is_summer(now)
    if summer:
        _, close_h = _parse_weekday_hour(cfg.get("summer_close", _DEFAULTS["summer_close"]))
    else:
        _, close_h = _parse_weekday_hour(cfg.get("winter_close", _DEFAULTS["winter_close"]))
    if close_h < 0:
        close_h = 5 if summer else 6
    # 下一个 close_h:00（今天或明天），即每日休市时刻
    close_dt = now.replace(hour=close_h, minute=0, second=0, microsecond=0)
    if close_dt <= now:
        close_dt += timedelta(days=1)
    return close_dt


def minutes_to_mt5_close():
    """距离下一次 MT5 休市还有多少分钟（float）；当前已休市/检测关闭返回 None。"""
    dt = get_next_mt5_close_dt()
    if dt is None:
        return None
    return (dt - datetime.now(_BJT)).total_seconds() / 60.0


def minutes_since_mt5_open():
    """距离最近一次 MT5 开市/日级重开已过多少分钟（float）；当前已休市/检测关闭返回 None。

    日级 rollover：每天 close_h:00（夏05:00/冬06:00）休市后立即重开，
    故该时刻即最近一次"重开"边界；周末休市 → 周一 open_h:00 重开。
    夏/冬令时由 _is_summer 自动处理。
    """
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return None
    is_open, _ = is_bybit_trading_hours()
    if not is_open:
        return None
    now = datetime.now(_BJT)
    summer = _is_summer(now)
    if summer:
        _, close_h = _parse_weekday_hour(cfg.get("summer_close", _DEFAULTS["summer_close"]))
        _, open_h = _parse_weekday_hour(cfg.get("summer_open", _DEFAULTS["summer_open"]))
    else:
        _, close_h = _parse_weekday_hour(cfg.get("winter_close", _DEFAULTS["winter_close"]))
        _, open_h = _parse_weekday_hour(cfg.get("winter_open", _DEFAULTS["winter_open"]))
    if close_h < 0:
        close_h = 5 if summer else 6
    if open_h < 0:
        open_h = 6 if summer else 7
    # 最近一次日级 rollover 边界（<= now）
    daily = now.replace(hour=close_h, minute=0, second=0, microsecond=0)
    if daily > now:
        daily -= timedelta(days=1)
    # 本周一开市边界
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=open_h, minute=0, second=0, microsecond=0)
    boundary = daily
    if monday <= now and monday > daily:
        boundary = monday
    return (now - boundary).total_seconds() / 60.0
