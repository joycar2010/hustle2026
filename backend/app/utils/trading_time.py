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
_HOLIDAY_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'mt5_holiday_schedule.json')

# 收盘前安全停缓冲(夏令时强制特殊时间点，数值不可随意改动):
# 距收盘<=SOFT 软停(仅停"一直运行"的，允许手动重启运行至HARD)；<=HARD 硬停(全部停，禁止启动)。
# continuous_executor 的软/硬停判定与 strategy_resume_service 的"自动恢复禁入"闸门共用此处常量，避免两处数值漂移。
SOFT_STOP_BUFFER_MIN = 15.0
HARD_STOP_BUFFER_MIN = 5.0

# Defaults (Beijing Time)
_DEFAULTS = {
    "enabled": True,
    "summer_open": "周一 06:00",
    "summer_close": "周六 05:00",
    "winter_open": "周一 07:00",
    "winter_close": "周六 06:00",
}


# market_closure.json mtime 缓存(2026-07-04): 消除每次调用的文件读+JSON解析(27μs)开销。
# 仅 os.stat 取 mtime(~1-2μs) 判文件是否变化, 未变返回缓存合并结果; 变了才重解析。
# 优于固定TTL: 保留热读即时性(改配置下一次调用即生效, 不等TTL), 省同样解析开销, 判定零改。
# 所有调用方均 cfg.get(...) 只读, 返回共享缓存对象安全。
_config_cache = {"mtime": None, "data": None}


def _load_config() -> dict:
    """Load market closure config from JSON file, fall back to defaults.
    基于 mtime 缓存: 文件未变则返回上次解析结果(避免重复读+解析), 变了自动重载(热读即时)。"""
    try:
        _mt = os.stat(_CONFIG_PATH).st_mtime
        if _config_cache["data"] is not None and _config_cache["mtime"] == _mt:
            return _config_cache["data"]
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and "config" in cfg:
            cfg = cfg["config"]
        merged = {**_DEFAULTS, **cfg}
        _config_cache["data"] = merged
        _config_cache["mtime"] = _mt
        return merged
    except Exception:
        # 读/解析/stat 任一失败 → 有旧缓存用旧缓存(避免抖动), 否则回退默认(fail-safe)
        if _config_cache["data"] is not None:
            return _config_cache["data"]
        return dict(_DEFAULTS)


def _pair_weekly_open_h(cfg: dict, pair_code, summer: bool, default_open_h: int) -> int:
    """周一(周末后)开市小时 per-pair(2026-07-04)。
    黄金/白银 周一06:00(夏)/07:00(冬); 油气(CL/BZ/NG) 周一08:00/09:00。
    数据源=config/market_closure.json 的 "pairs" 段(pair_code→{summer_open_h,winter_open_h});
    缺失→回退全局 default_open_h(黄金语义, 零回归)。仅影响【周一开市】判定, 不影响日级重开/收盘。"""
    if not pair_code:
        return default_open_h
    try:
        pairs = cfg.get("pairs") or {}
        po = pairs.get(pair_code) or pairs.get(str(pair_code).upper())
        if not po:
            return default_open_h
        k = "summer_open_h" if summer else "winter_open_h"
        v = po.get(k)
        return int(v) if v is not None else default_open_h
    except Exception:
        return default_open_h


def _pair_daily_reopen_h(cfg: dict, pair_code, summer: bool, default_reopen_h: int) -> int:
    """日级重开小时 per-pair(2026-07-04, 布伦特专用)。多数品种每日 rollover 重开 = 全局(北京06:00夏)。
    布伦特(BZ)特殊: 周二~周五日级重开北京08:00夏/09:00冬(IC/Bybit均如此, 比其它品种晚2h)。
    数据源=market_closure.json "pairs"段的 summer_daily_reopen_h/winter_daily_reopen_h;
    缺失→回退全局 default_reopen_h(零回归)。【仅影响周二~周日的日级窗, 不影响周一(周末后)开市】。"""
    if not pair_code:
        return default_reopen_h
    try:
        pairs = cfg.get("pairs") or {}
        po = pairs.get(pair_code) or pairs.get(str(pair_code).upper())
        if not po:
            return default_reopen_h
        k = "summer_daily_reopen_h" if summer else "winter_daily_reopen_h"
        v = po.get(k)
        return int(v) if v is not None else default_reopen_h
    except Exception:
        return default_reopen_h


# 节假日表缓存(60s): 文件几乎不变, 但每60s回读以支持运行中热更新(人工填表后无需重启)。
_holiday_cache = {"ts": 0.0, "data": None}
_HOLIDAY_CACHE_TTL = 60.0


def _load_holiday_windows() -> list:
    """读取黄金节假日提前停市表 config/mt5_holiday_schedule.json, 返回 windows 列表。
    文件缺失/损坏/禁用 → 返回 []（=不挡任何交易, 安全降级到原行为）。带60s缓存支持热更新。"""
    import time as _t
    now = _t.time()
    if _holiday_cache["data"] is not None and (now - _holiday_cache["ts"]) < _HOLIDAY_CACHE_TTL:
        return _holiday_cache["data"]
    windows = []
    try:
        with open(_HOLIDAY_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and cfg.get("enabled", True):
            windows = cfg.get("windows", []) or []
    except Exception:
        windows = []  # 缺失/损坏 → 不挡交易(安全降级)
    _holiday_cache["data"] = windows
    _holiday_cache["ts"] = now
    return windows


def check_holiday_closure(now_bjt=None) -> tuple[bool, str]:
    """节假日提前停市检查(北京时间)。返回 (in_closure, name)。
    落在任一 [start, end) 北京时间窗口内 → (True, 窗口名)。无匹配 → (False, "")。
    解析失败的单条窗口跳过(不影响其他窗口/不误挡)。"""
    if now_bjt is None:
        now_bjt = datetime.now(_BJT)
    for w in _load_holiday_windows():
        try:
            s = datetime.strptime(w["start"], "%Y-%m-%d %H:%M").replace(tzinfo=_BJT)
            e = datetime.strptime(w["end"], "%Y-%m-%d %H:%M").replace(tzinfo=_BJT)
            if s <= now_bjt < e:
                return True, str(w.get("name", "节假日停市"))
        except Exception:
            continue
    return False, ""


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


def is_bybit_trading_hours(pair_code=None) -> tuple[bool, str]:
    """
    Check if Bybit MT5 is currently in trading hours based on config.
    pair_code(2026-07-04 多交易对): 传入则按该品种【周一开市小时】判定(金06:00/油气08:00夏);
    None=全局黄金行为(零回归)。日级 rollover 重开小时与收盘小时始终全局(所有品种一致)。

    Returns:
        tuple: (is_open: bool, message: str)
    """
    cfg = _load_config()

    if not cfg.get("enabled", True):
        return True, "停市检测已关闭"

    now_bjt = datetime.now(_BJT)

    # 节假日提前停市闸(20260620): 黄金 COMEX 节假日提前收盘期间, 币安仍可成交而 MT5 拒单(10018)
    # →单腿。事前按已知 CME 假期日历(config/mt5_holiday_schedule.json)直接判休市, 从源头规避。
    # 此判定先于周/日级常规判定; 所有调用方(策略主循环/恢复服务/广播)经此自动停 A 侧下单。
    _hol, _hol_name = check_holiday_closure(now_bjt)
    if _hol:
        return False, f"MT5休市中（节假日提前停市：{_hol_name}）"

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

    # 周一(周末后)开市小时=per-pair(布伦特周一不特殊=全局); 日级重开小时=per-pair(布伦特周二~晚2h)。
    weekly_open_h = _pair_weekly_open_h(cfg, pair_code, summer, open_h)
    daily_reopen_h = _pair_daily_reopen_h(cfg, pair_code, summer, open_h)

    # 日级休市闸(20260612; 20260704 日期感知): 每日 close_h:00 收市 → 重开小时才开市。
    # 【周一】重开边界用 weekly_open_h(周末后首开; 布伦特周一=全局06:00正常, 不特殊);
    # 【周二~】重开边界用 daily_reopen_h(日级 rollover; 布伦特=08:00夏/09:00冬, 其它品种=全局06:00)。
    # 金银/WTI/NG 的 weekly=daily=全局, 无差异零回归; 仅布伦特周二~五在此多停到08:00(消除其
    # 06:00-08:00 实际休市却判开市→单腿 的活跃bug)。
    _eff_reopen_h = weekly_open_h if weekday == open_wd else daily_reopen_h
    if close_h <= hour < _eff_reopen_h:
        return False, f"MT5休市中（{season_label}，日级休市{close_h:02d}:00-{_eff_reopen_h:02d}:00）"

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

    # Monday before open hour = closed。周一开市小时【per-pair】(金06/油气08夏)。
    if weekday == open_wd and hour < weekly_open_h:
        return False, f"MT5休市中（{season_label}，周一{weekly_open_h:02d}:00开市）"

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


def minutes_since_mt5_open(pair_code=None):
    """距离最近一次 MT5 开市/日级重开已过多少分钟（float）；当前已休市/检测关闭返回 None。

    日级 rollover：每天 close_h:00（夏05:00/冬06:00）休市后立即重开(日级重开=全局 open_h)，
    故该时刻即最近一次"重开"边界；周末休市 → 周一 开市小时重开(per-pair: 金06/油气08夏)。
    夏/冬令时由 _is_summer 自动处理。pair_code(2026-07-04): 周一开市边界 per-pair, 使油气
    的预热延迟从其真实开市(周一08:00)起算而非黄金06:00。
    """
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return None
    is_open, _ = is_bybit_trading_hours(pair_code)
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
    # 最近一次日级"重开"边界(<= now): 日期感知——周一用weekly_open_h(周末后首开), 周二~用
    # per-pair daily_reopen(布伦特08:00夏, 其它=全局06:00)。使布伦特预热周二~从其真实08:00起算。
    _weekly_open_h = _pair_weekly_open_h(cfg, pair_code, summer, open_h)
    _daily_reopen_h = _pair_daily_reopen_h(cfg, pair_code, summer, open_h)
    _eff_daily_h = _weekly_open_h if now.weekday() == 0 else _daily_reopen_h
    daily = now.replace(hour=_eff_daily_h, minute=0, second=0, microsecond=0)
    if daily > now:
        daily -= timedelta(days=1)
    # 本周一开市边界: 开市小时 per-pair(布伦特周一=全局06:00)。
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=_weekly_open_h, minute=0, second=0, microsecond=0)
    boundary = daily
    if monday <= now and monday > daily:
        boundary = monday
    return (now - boundary).total_seconds() / 60.0


_OPEN_WARMUP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "open_warmup.json")
_OPEN_WARMUP_DEFAULTS = {"XAU": 1.0, "ICXAU": 2.0}


# 对冲 B 腿平台 → 预热分钟 的内置回退映射(2026-07-04): Bybit(平台2)+1 / ICMarkets(平台3)+2。
# 可被 open_warmup.json 的 "by_platform" 段覆盖(热改)。用于【未显式配置的新对】自动取值。
_WARMUP_BY_PLATFORM_DEFAULT = {2: 1.0, 3: 2.0}


def _warmup_by_hedge_platform(pair_code, by_platform_cfg):
    """按该对【对冲 B 腿平台】自动回退预热分钟。hedging_pair_service 纯内存(O(1),零DB),
    热循环安全; 函数内延迟 import + fail-safe(服务未加载/对不存在→None, 交由上层走 default)。"""
    try:
        from app.services.hedging_pair_service import hedging_pair_service
        p = hedging_pair_service.get_pair(pair_code)
        if not p or not getattr(p, "symbol_b", None):
            return None
        plat = int(p.symbol_b.platform_id)
        # 优先用配置的 by_platform(键为字符串), 再回退内置
        if by_platform_cfg and str(plat) in by_platform_cfg:
            return float(by_platform_cfg[str(plat)])
        if plat in _WARMUP_BY_PLATFORM_DEFAULT:
            return float(_WARMUP_BY_PLATFORM_DEFAULT[plat])
    except Exception:
        pass
    return None


def open_warmup_minutes(pair_code):
    # 开市后该交易对需等待的预热分钟数; config/open_warmup.json 可热改。
    # 回退优先级(2026-07-04): ①显式配置该对 → 用它(向后兼容/手动覆盖);
    # ②未显式配置 → 按【对冲B腿平台】自动(Bybit+1/IC+2, 新增对无需手工配即生效);
    # ③都拿不到 → default → 内置默认 → 0。
    try:
        with open(_OPEN_WARMUP_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and "config" in cfg and isinstance(cfg["config"], dict):
            cfg = cfg["config"]
        # ① 显式配置优先(值须为数值, 排除 _comment/by_platform/default 等非对键的误命中)
        if pair_code in cfg and isinstance(cfg.get(pair_code), (int, float)):
            return float(cfg[pair_code])
        # ② 按对冲 B 腿平台自动回退(新增对无需手工配)
        _auto = _warmup_by_hedge_platform(pair_code, cfg.get("by_platform"))
        if _auto is not None:
            return _auto
        # ③ default
        if "default" in cfg:
            return float(cfg["default"])
    except Exception:
        pass
    # 兜底: 内置默认(仍先试平台自动, 再 0)
    _auto2 = _warmup_by_hedge_platform(pair_code, None)
    if _auto2 is not None:
        return _auto2
    return float(_OPEN_WARMUP_DEFAULTS.get(pair_code, 0.0))
