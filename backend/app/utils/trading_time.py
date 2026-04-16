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


def _is_summer(month: int) -> bool:
    """April (4) through October (10) = summer."""
    return 4 <= month <= 10


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

    summer = _is_summer(month)
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
    summer = _is_summer(month)
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
