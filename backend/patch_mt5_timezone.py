"""Fix MT5 server timestamp timezone offset (EET/EEST DST-aware)."""

# ============================================================
# Fix 1: time_utils.py — add mt5_server_ts_to_utc() + update mt5_time_to_beijing()
# ============================================================
path1 = '/data/hustle2026/backend/app/utils/time_utils.py'
with open(path1, 'r') as f:
    content = f.read()

# 1a: Add zoneinfo import after existing imports
old_import = "from datetime import datetime, timezone\nfrom typing import Optional"
new_import = """from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# MT5 broker servers use EET/EEST (UTC+2 winter, UTC+3 summer)
_MT5_SERVER_TZ = ZoneInfo("Europe/Helsinki")


def mt5_server_ts_to_utc(raw_ts: int) -> int:
    \"\"\"Convert MT5 bridge deal.time (broker server local time) to UTC Unix timestamp.

    MT5 deal.time is a Unix-like timestamp encoded in broker server timezone (EET/EEST),
    not UTC. This function converts it to a true UTC timestamp, handling DST automatically.
    \"\"\"
    naive = datetime.utcfromtimestamp(raw_ts)
    local = naive.replace(tzinfo=_MT5_SERVER_TZ)
    return int(local.astimezone(timezone.utc).timestamp())"""

assert content.count(old_import) == 1, f"[1a] Expected 1 match, found {content.count(old_import)}"
content = content.replace(old_import, new_import)
print("[1a] Added zoneinfo import + mt5_server_ts_to_utc()")

# 1b: Replace mt5_time_to_beijing() with DST-aware version
old_func = """def mt5_time_to_beijing(mt5_timestamp: int) -> str:
    \"\"\"
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
    \"\"\"
    from datetime import timedelta
    # MT5时间戳转为datetime（假设为UTC）
    mt5_dt = datetime.fromtimestamp(mt5_timestamp, tz=timezone.utc)
    # 减去2小时得到真实UTC时间（因为MT5服务器是UTC+2）
    utc_dt = mt5_dt - timedelta(hours=2)
    # 加8小时得到北京时间
    beijing_dt = utc_dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")"""

new_func = """def mt5_time_to_beijing(mt5_timestamp: int) -> str:
    \"\"\"MT5时间戳 → 北京时间字符串（DST-aware）

    MT5 deal.time 是 broker server local time (EET/EEST) 编码的 Unix-like 时间戳。
    通过 zoneinfo 自动处理夏令时（UTC+2 冬 / UTC+3 夏）。
    \"\"\"
    utc_ts = mt5_server_ts_to_utc(mt5_timestamp)
    utc_dt = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
    beijing_dt = utc_dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")"""

assert content.count(old_func) == 1, f"[1b] Expected 1 match, found {content.count(old_func)}"
content = content.replace(old_func, new_func)
print("[1b] Replaced mt5_time_to_beijing() with DST-aware version")

with open(path1, 'w') as f:
    f.write(content)
print("[1] time_utils.py patched\n")

# ============================================================
# Fix 2: pnl.py — update _mt5_ts_to_beijing_date()
# ============================================================
path2 = '/data/hustle2026/backend/app/api/v1/pnl.py'
with open(path2, 'r') as f:
    content2 = f.read()

old_pnl_func = """def _mt5_ts_to_beijing_date(ts_sec: int) -> str:
    \"\"\"MT5 服务器时间（UTC+2/+3）→ 北京时间日期\"\"\"
    # MT5 deal.time 是 UTC+0 的 unix timestamp（Bridge 已转为 UTC）
    dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
    beijing = dt + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d")"""

new_pnl_func = """def _mt5_ts_to_beijing_date(ts_sec: int) -> str:
    \"\"\"MT5 服务器时间（EET/EEST）→ 北京时间日期（DST-aware）\"\"\"
    from app.utils.time_utils import mt5_server_ts_to_utc
    utc_ts = mt5_server_ts_to_utc(ts_sec)
    dt = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
    beijing = dt + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d")"""

assert content2.count(old_pnl_func) == 1, f"[2] Expected 1 match, found {content2.count(old_pnl_func)}"
content2 = content2.replace(old_pnl_func, new_pnl_func)
print("[2] pnl.py _mt5_ts_to_beijing_date() patched")

with open(path2, 'w') as f:
    f.write(content2)

print("\n✅ Both files patched. Restart hustle-python to apply.")
